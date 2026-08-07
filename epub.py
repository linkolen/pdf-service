"""
Reflowable EPUB 3 composition for the interior book (companion to the KDP
interior PDF in compose.py). Deliberately NOT fixed-layout: KDP's own
troubleshooting docs say "We do not support the 'Fixed Layout' tag in Open
Packaging Format files (.opf)" for directly-uploaded EPUBs (fixed-layout
Kindle books are expected to go through Kindle Create instead, which packages
its own proprietary KPF), and KDP's Arabic-specific guidance separately asks
for "reflowable" content, not "scanned image-based" pages. So each story page
is normal document flow -- an inline image followed by a paragraph of text,
with a page-break hint between pages -- not an absolutely-positioned
full-bleed background with a text overlay. Built by hand with zipfile/jinja2
rather than a dependency: an EPUB is just a zip with a fixed internal
structure, and this keeps requirements.txt minimal.
"""

from __future__ import annotations

import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader

from imaging import resize_and_encode_jpeg

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates" / "epub"
FONT_FILE = BASE_DIR / "fonts" / "NotoNaskhArabic[wght].ttf"

# KDP's reflowable image guidance (spec: images should occupy a healthy
# fraction of the screen width) doesn't set a hard pixel ceiling; this is
# comfortably sharp on any Kindle screen without bloating the file the way an
# uncapped source image (Gemini/manual uploads are often 3000px+) would.
PAGE_IMAGE_MAX_DIMENSION_PX = 1600

# Page art is painterly/photographic AI illustration, not line art or text, so
# JPEG at a high quality setting is visually indistinguishable from the PNG it
# replaces while landing at a fraction of the size -- PNG's lossless DEFLATE
# compresses continuous-tone images poorly. 4:4:4 (no chroma subsampling)
# avoids color fringing at illustration edges.
PAGE_IMAGE_JPEG_QUALITY = 92


@dataclass
class EpubPageSpec:
    page_number: int
    image_key: str
    image_bytes: bytes
    text_ar: str


def _image_filename(page_number: int) -> str:
    # Always .jpg: resize_and_encode_jpeg re-encodes every page image to
    # JPEG, so the on-disk extension must match regardless of the source
    # upload's format.
    return f"page-{page_number:04d}.jpg"


def build_interior_epub(book_id: str, title_ar: str, pages: List[EpubPageSpec]) -> bytes:
    """Render one reflowable EPUB3 (image + text per story page, in document
    flow) and return its bytes (not written to storage here -- the caller
    owns where it lands)."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

    manifest_pages = [
        {
            "page_number": page.page_number,
            "id": f"page-{page.page_number:04d}",
            "xhtml_filename": f"page-{page.page_number:04d}.xhtml",
            "image_filename": _image_filename(page.page_number),
            "image_media_type": "image/jpeg",
        }
        for page in pages
    ]

    book_uuid = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'arabic-kids-book:{book_id}')}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    opf_xml = env.get_template("content.opf.xml").render(
        book_uuid=book_uuid,
        title_ar=title_ar,
        modified=modified,
        pages=manifest_pages,
    )
    nav_xhtml = env.get_template("nav.xhtml").render(title_ar=title_ar, pages=manifest_pages)
    css = env.get_template("style.css").render()
    container_xml = (TEMPLATES_DIR / "container.xml").read_text(encoding="utf-8")
    page_template = env.get_template("page.xhtml")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first, uncompressed, with no extra field -- the
        # spec-mandated way EPUB readers sniff the zip as an EPUB.
        zf.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip", zipfile.ZIP_STORED
        )
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/css/style.css", css)
        zf.write(FONT_FILE, "OEBPS/fonts/NotoNaskhArabic.ttf")

        for page, manifest_page in zip(pages, manifest_pages):
            page_xhtml = page_template.render(
                page_number=page.page_number,
                image_filename=manifest_page["image_filename"],
                text_ar=page.text_ar,
                is_first_page=(page.page_number == pages[0].page_number),
            )
            fitted_image_bytes = resize_and_encode_jpeg(
                page.image_bytes, PAGE_IMAGE_MAX_DIMENSION_PX, PAGE_IMAGE_JPEG_QUALITY
            )
            zf.writestr(f"OEBPS/text/{manifest_page['xhtml_filename']}", page_xhtml)
            zf.writestr(f"OEBPS/images/{manifest_page['image_filename']}", fitted_image_bytes)

    return buf.getvalue()
