"""
Multi-page interior composition (spec Section 9, step 2) and wraparound cover
composition (Section 9, step 6): fetch stored images from MinIO, lay them out
per KDP's rules, and render PDFs back to MinIO.
"""

from __future__ import annotations

import base64
import math
import mimetypes
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF
from jinja2 import Environment, FileSystemLoader
from PIL import Image
from weasyprint import HTML

import layout
from epub import EpubPageSpec, build_interior_epub
from imaging import fit_and_encode_jpeg, prepare_coloring_page_png
from storage import Storage

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
FONT_PATH = "../fonts/NotoNaskhArabic[wght].ttf"
FONT_EN_PATH = "../fonts/DejaVuSerif.ttf"


@dataclass
class PageSpec:
    page_number: int
    image_key: str
    text_ar: str


@dataclass
class ComposeInteriorResult:
    pdf_key: str
    epub_key: str


@dataclass
class ComposeCoverResult:
    pdf_key: str
    jpeg_key: str


@dataclass
class CoverOverlay:
    """Kids-Heaven front-cover copy deck (Brain Quest style zones).

    All strings are ready-to-render in `language` ("ar" RTL Noto Naskh,
    "en" LTR DejaVu Sans). When None, compose_cover keeps its legacy
    behavior (bare art, optional title/author line only).
    """

    brand: str = "KIDS HEAVEN"
    authority: str = ""
    title: str = ""
    age: str = ""
    edition: str = ""
    skills: Optional[List[str]] = None
    starburst: str = ""
    comes_head: str = "COMES WITH:"
    comes_with: Optional[List[str]] = None


EBOOK_COVER_DPI = 300

# KDP's interior image floor (spec Section 6) -- exceeding it bloats the PDF
# with pixels no printer will reproduce. Uploaded/generated art is often well
# above this (Gemini output upscaled to clear the floor can land at 400+ DPI),
# so every page image is capped down to exactly this before embedding.
# math.ceil in the pixel-target calc below guarantees the floor is never
# undershot by a fraction-of-a-pixel rounding error.
INTERIOR_PRINT_DPI = 300
INTERIOR_JPEG_QUALITY = 92
EBOOK_COVER_JPEG_QUALITY = 92


def _data_uri(image_bytes: bytes, image_key: str) -> str:
    mime, _ = mimetypes.guess_type(image_key)
    mime = mime or "image/png"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def compose_interior(
    book_id: str,
    pages: List[PageSpec],
    trim_width_in: float = 8.5,
    trim_height_in: float = 8.5,
    bleed_in: float = 0.125,
    title_ar: Optional[str] = None,
    book_type: str = "story",
    full_bleed_images: bool = False,
    language: str = "ar",
    storage: Optional[Storage] = None,
) -> ComposeInteriorResult:
    """Fetch each page's image from MinIO `uploads`, render the combined
    interior as both a KDP-ready print PDF and a reflowable Kindle EPUB,
    write both to MinIO `outputs`, and return their object keys.

    book_type="story": each page is a full-bleed illustration with an RTL
    paragraph overlay (the original picture-book layout).
    book_type="coloring": each page is a bordered, contained black-and-white
    line-art frame with an optional short caption underneath -- no
    full-bleed background (CLAUDE.md's Book types section), unless
    full_bleed_images is set, in which case the line art fills the page
    edge-to-edge like a story page (still thresholded to pure B&W)."""
    for warning in layout.validate_page_count(len(pages)):
        print(f"[compose_interior] warning: {warning}")

    store = storage or Storage()

    page_width_in = trim_width_in + 2 * bleed_in
    page_height_in = trim_height_in + 2 * bleed_in
    total_pages = len(pages)

    # Full-bleed background covers the whole page, not just the trim area.
    page_width_px = math.ceil(page_width_in * INTERIOR_PRINT_DPI)
    page_height_px = math.ceil(page_height_in * INTERIOR_PRINT_DPI)

    rendered_pages = []
    epub_pages = []
    for page in sorted(pages, key=lambda p: p.page_number):
        image_bytes = store.get_image_bytes(page.image_key)
        margins = layout.get_page_margins(page.page_number, total_pages)

        # Activity books embed the full-resolution puzzle image (no
        # downscale to safe area) to preserve ≥300 DPI at trim size.
        # Coloring books use the bordered contain-fit frame.
        if book_type == "activity":
            image_data_uri = _data_uri(image_bytes, "page.png")
        elif book_type == "coloring" and full_bleed_images:
            # Full-bleed line art: threshold to pure B&W, then cover-fit the
            # whole page like a story page (no border frame).
            fitted_bytes = fit_and_encode_jpeg(
                prepare_coloring_page_png(
                    image_bytes, page_width_px, page_height_px
                ),
                page_width_px,
                page_height_px,
                INTERIOR_JPEG_QUALITY,
            )
            image_data_uri = _data_uri(fitted_bytes, "page.jpg")
        elif book_type == "coloring":
            safe_width_px = math.ceil(
                (page_width_in - margins.left_in - margins.right_in) * INTERIOR_PRINT_DPI
            )
            safe_height_px = math.ceil(
                (page_height_in - margins.top_in - margins.bottom_in) * INTERIOR_PRINT_DPI
            )
            fitted_bytes = prepare_coloring_page_png(image_bytes, safe_width_px, safe_height_px)
            image_data_uri = _data_uri(fitted_bytes, "page.png")
        else:
            fitted_bytes = fit_and_encode_jpeg(
                image_bytes, page_width_px, page_height_px, INTERIOR_JPEG_QUALITY
            )
            image_data_uri = _data_uri(fitted_bytes, "page.jpg")

        rendered_pages.append(
            {
                "page_number": page.page_number,
                "image_data_uri": image_data_uri,
                "text_ar": page.text_ar,
                "margins": margins,
            }
        )
        # Activity pages carry their caption inside the puzzle PNG's banner;
        # emitting it again as EPUB text would duplicate it.
        epub_pages.append(
            EpubPageSpec(
                page_number=page.page_number,
                image_key=page.image_key,
                image_bytes=image_bytes,
                text_ar=page.text_ar if book_type != "activity" else "",
            )
        )

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("interior.html")
    html_str = template.render(
        page_width_in=page_width_in,
        page_height_in=page_height_in,
        font_path=FONT_PATH,
        font_en_path=FONT_EN_PATH,
        book_type=book_type,
        full_bleed_images=full_bleed_images,
        language=language,
        pages=rendered_pages,
    )

    pdf_bytes = HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf()
    pdf_key = f"{book_id}/interior.pdf"
    store.put_pdf_bytes(pdf_key, pdf_bytes)

    epub_bytes = build_interior_epub(
        book_id=book_id,
        title_ar=title_ar or book_id,
        pages=epub_pages,
        book_type=book_type,
        language=language,
    )
    epub_key = f"{book_id}/interior.epub"
    store.put_epub_bytes(epub_key, epub_bytes)

    return ComposeInteriorResult(pdf_key=pdf_key, epub_key=epub_key)


def _rasterize_front_cover_jpeg(
    pdf_bytes: bytes,
    front_panel_width_in: float,
    cover_height_in: float,
    dpi: int = EBOOK_COVER_DPI,
) -> bytes:
    """Rasterizes just the front-cover panel (the rightmost strip of the
    flattened back|spine|front spread, see compose_cover) out of the
    rendered cover PDF. Used for KDP's Kindle eBook cover upload
    (spec: JPEG, RGB, see config/kdp_rules.json's "ebook_cover")."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page = doc[0]
        page_width_pt = page.rect.width
        page_height_pt = page.rect.height
        front_width_pt = front_panel_width_in * 72
        clip = fitz.Rect(page_width_pt - front_width_pt, 0, page_width_pt, page_height_pt)
        zoom = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, colorspace=fitz.csRGB)
        for warning in layout.validate_ebook_cover_dimensions(pix.width, pix.height):
            print(f"[compose_cover] warning: {warning}")

        # pix.tobytes("jpg") has no quality/DPI-tag control and defaults to
        # embedding 96 DPI in the JFIF header; KDP's ebook cover spec lists
        # 72 DPI as the required tag (the pixel dimensions above are what
        # actually govern quality -- this tag is a vestigial metadata field,
        # but it's cheap to get exactly right).
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        out = BytesIO()
        img.save(
            out,
            format="JPEG",
            quality=EBOOK_COVER_JPEG_QUALITY,
            subsampling=0,
            optimize=True,
            dpi=(72, 72),
        )
        return out.getvalue()
    finally:
        doc.close()


def compose_cover(
    book_id: str,
    image_key: str,
    page_count: int,
    paper_type: str,
    trim_width_in: float = 8.5,
    trim_height_in: float = 8.5,
    bleed_in: float = 0.125,
    cover_title_text: Optional[str] = None,
    cover_author_text: Optional[str] = None,
    language: str = "ar",
    storage: Optional[Storage] = None,
    overlay: Optional[CoverOverlay] = None,
) -> ComposeCoverResult:
    """Fetch the single wraparound cover illustration from MinIO `uploads`,
    size the page to KDP's back+spine+front formula (Section 7), render one
    PDF for print, rasterize that same front panel to a JPEG for KDP's
    Kindle eBook cover upload, write both to MinIO `outputs`, and return
    their object keys. By default no text is overlaid -- the cover art
    carries everything. If cover_title_text/cover_author_text are set
    (opt-in via the UI), the Arabic title/author are drawn on the front
    panel's upper area in the embedded Arabic font. If `overlay` is set
    (Kids-Heaven activity-book copy deck), the full Brain Quest style zone
    set -- authority band, brand, theme title, age pill, edition pill,
    skill rail, starburst, comes-with box -- is drawn on the front panel
    instead (legacy title/author block is skipped to avoid duplication)."""
    store = storage or Storage()

    spine_in = layout.spine_width_in(page_count, paper_type)
    cover_width_in = layout.cover_width_in(trim_width_in, bleed_in, spine_in)
    cover_height_in = layout.cover_height_in(trim_height_in, bleed_in)

    # Flattened print files always read back-cover | spine | front-cover left
    # to right -- a fixed manufacturing convention, independent of the book's
    # own (RTL) reading direction. The front panel is the rightmost strip.
    front_panel_width_in = trim_width_in + bleed_in
    front_left_in = round(cover_width_in - front_panel_width_in, 3)

    image_bytes = store.get_image_bytes(image_key)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("cover.html")
    # Text overlay sits on the front (rightmost) panel, top area, centered
    # within it with a 0.4in safety margin from the trim/bleed edges.
    html_str = template.render(
        cover_width_in=cover_width_in,
        cover_height_in=cover_height_in,
        image_data_uri=_data_uri(image_bytes, image_key),
        cover_title_text=None if overlay else cover_title_text,
        cover_author_text=None if overlay else cover_author_text,
        language=language,
        cover_text_top_in=round(bleed_in + 0.5, 3),
        cover_text_right_in=round(bleed_in + 0.4, 3),
        cover_text_width_in=round(trim_width_in - 0.8, 3),
        front_left_in=front_left_in,
        front_width_in=round(front_panel_width_in, 3),
        front_burst_left_in=round(front_left_in + 0.5, 3),
        front_edition_left_in=round(front_left_in + 0.55, 3),
        overlay=overlay,
    )

    pdf_bytes = HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf()

    pdf_key = f"{book_id}/cover.pdf"
    store.put_pdf_bytes(pdf_key, pdf_bytes)

    jpeg_bytes = _rasterize_front_cover_jpeg(pdf_bytes, front_panel_width_in, cover_height_in)
    jpeg_key = f"{book_id}/cover.jpg"
    store.put_jpeg_bytes(jpeg_key, jpeg_bytes)

    return ComposeCoverResult(pdf_key=pdf_key, jpeg_key=jpeg_key)
