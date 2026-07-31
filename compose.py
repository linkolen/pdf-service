"""
Multi-page interior composition (spec Section 9, step 2) and wraparound cover
composition (Section 9, step 6): fetch stored images from MinIO, lay them out
per KDP's rules, and render PDFs back to MinIO.
"""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

import layout
from storage import Storage

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
FONT_PATH = "../fonts/NotoNaskhArabic[wght].ttf"


@dataclass
class PageSpec:
    page_number: int
    image_key: str
    text_ar: str


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
    storage: Optional[Storage] = None,
) -> str:
    """Fetch each page's image from MinIO `uploads`, render one combined
    interior PDF, write it to MinIO `outputs`, and return its object key."""
    for warning in layout.validate_page_count(len(pages)):
        print(f"[compose_interior] warning: {warning}")

    store = storage or Storage()

    page_width_in = trim_width_in + 2 * bleed_in
    page_height_in = trim_height_in + 2 * bleed_in
    total_pages = len(pages)

    rendered_pages = []
    for page in sorted(pages, key=lambda p: p.page_number):
        image_bytes = store.get_image_bytes(page.image_key)
        rendered_pages.append(
            {
                "page_number": page.page_number,
                "image_data_uri": _data_uri(image_bytes, page.image_key),
                "text_ar": page.text_ar,
                "margins": layout.get_page_margins(page.page_number, total_pages),
            }
        )

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("interior.html")
    html_str = template.render(
        page_width_in=page_width_in,
        page_height_in=page_height_in,
        font_path=FONT_PATH,
        pages=rendered_pages,
    )

    pdf_bytes = HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf()

    output_key = f"{book_id}/interior.pdf"
    store.put_pdf_bytes(output_key, pdf_bytes)
    return output_key


def compose_cover(
    book_id: str,
    image_key: str,
    title_ar: str,
    page_count: int,
    paper_type: str,
    trim_width_in: float = 8.5,
    trim_height_in: float = 8.5,
    bleed_in: float = 0.125,
    storage: Optional[Storage] = None,
) -> str:
    """Fetch the single wraparound cover illustration from MinIO `uploads`,
    size the page to KDP's back+spine+front formula (Section 7), overlay the
    Arabic title on the front-cover panel, render one PDF, write it to MinIO
    `outputs`, and return its object key."""
    store = storage or Storage()

    spine_in = layout.spine_width_in(page_count, paper_type)
    cover_width_in = layout.cover_width_in(trim_width_in, bleed_in, spine_in)
    cover_height_in = layout.cover_height_in(trim_height_in, bleed_in)

    # Flattened print files always read back-cover | spine | front-cover left
    # to right -- a fixed manufacturing convention, independent of the book's
    # own (RTL) reading direction. The front panel is the rightmost strip.
    front_panel_width_in = trim_width_in + bleed_in
    safe_margin_in = layout.outside_margin_in(bleed=True)

    image_bytes = store.get_image_bytes(image_key)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("cover.html")
    html_str = template.render(
        cover_width_in=cover_width_in,
        cover_height_in=cover_height_in,
        front_panel_width_in=front_panel_width_in,
        safe_margin_in=safe_margin_in,
        font_path=FONT_PATH,
        image_data_uri=_data_uri(image_bytes, image_key),
        title_ar=title_ar,
    )

    pdf_bytes = HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf()

    output_key = f"{book_id}/cover.pdf"
    store.put_pdf_bytes(output_key, pdf_bytes)
    return output_key
