"""
Manual integration check for milestone 2: seed a local MinIO with placeholder
page images, run compose_interior against it, and pull the resulting PDF back
down for inspection.

Point MINIO_ENDPOINT at wherever `docker run minio/minio` is listening
(defaults to localhost:9000, matching storage.py's defaults). Run inside the
pdf-service image so weasyprint/minio are available, e.g.:

    docker run --rm --network host \
      -v "$(pwd)/output:/app/output" \
      pdf-service-milestone1 python scripts/seed_and_compose.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent.parent))

from compose import PageSpec, compose_interior
from storage import OUTPUTS_BUCKET, Storage

BOOK_ID = "test-book-001"
PAGE_COUNT = 24
PAGE_PX = 2625  # 8.75in @ 300dpi, matches milestone-1 trim+bleed

PALETTES = [
    ((142, 202, 230), (2, 62, 138)),
    ((255, 183, 3), (251, 133, 0)),
    ((131, 197, 190), (2, 48, 71)),
]

STORY_LINES = [
    "في يومٍ مشمسٍ، خرجت الأرنبة الصغيرة تلعب بين الزهور.",
    "قابلت صديقتها السلحفاة عند النهر الجميل.",
    "لعبتا معاً حتى غروب الشمس الذهبية.",
    "ثم عادتا إلى البيت وهما تضحكان بسعادة.",
]


def make_placeholder_png(page_number: int) -> bytes:
    top, bottom = PALETTES[page_number % len(PALETTES)]
    img = Image.new("RGB", (PAGE_PX, PAGE_PX), top)
    draw = ImageDraw.Draw(img)
    for y in range(PAGE_PX):
        t = y / PAGE_PX
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        draw.line([(0, y), (PAGE_PX, y)], fill=(r, g, b))
    draw.text((100, 100), f"page {page_number}", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    store = Storage()

    pages = []
    for n in range(1, PAGE_COUNT + 1):
        key = f"{BOOK_ID}/page-{n}.png"
        store.put_image_bytes(key, make_placeholder_png(n))
        text = STORY_LINES[(n - 1) % len(STORY_LINES)]
        pages.append(PageSpec(page_number=n, image_key=key, text_ar=text))
        print(f"seeded {key}")

    output_key = compose_interior(BOOK_ID, pages, storage=store)
    print(f"composed -> {OUTPUTS_BUCKET}/{output_key}")

    pdf_bytes = store.client.get_object(OUTPUTS_BUCKET, output_key).read()
    out_path = Path(__file__).parent.parent / "output" / "interior.pdf"
    out_path.write_bytes(pdf_bytes)
    print(f"wrote {out_path} ({len(pdf_bytes)} bytes)")


if __name__ == "__main__":
    main()
