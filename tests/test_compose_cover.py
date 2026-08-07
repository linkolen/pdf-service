import io
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from compose import compose_cover


class FakeStorage:
    """In-memory stand-in for storage.Storage so compose_cover can be unit
    tested without a real MinIO -- WeasyPrint still runs for real."""

    def __init__(self, images: dict[str, bytes]):
        self._images = images
        self.written_pdfs: dict[str, bytes] = {}
        self.written_jpegs: dict[str, bytes] = {}

    def get_image_bytes(self, key: str) -> bytes:
        return self._images[key]

    def put_pdf_bytes(self, key: str, data: bytes) -> str:
        self.written_pdfs[key] = data
        return key

    def put_jpeg_bytes(self, key: str, data: bytes) -> str:
        self.written_jpegs[key] = data
        return key


def _make_png_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), (180, 90, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_compose_cover_writes_correctly_sized_pdf():
    image_key = "book-1/cover.png"
    storage = FakeStorage({image_key: _make_png_bytes(3000, 2625)})

    result = compose_cover(
        book_id="book-1",
        image_key=image_key,
        title_ar="أرنوب يتعلم المشاركة",
        page_count=24,
        paper_type="color",
        storage=storage,
    )

    assert result.pdf_key == "book-1/cover.pdf"
    assert result.pdf_key in storage.written_pdfs
    assert storage.written_pdfs[result.pdf_key][:4] == b"%PDF"


def test_compose_cover_writes_kdp_compliant_ebook_jpeg():
    image_key = "book-1/cover.png"
    storage = FakeStorage({image_key: _make_png_bytes(3000, 2625)})

    result = compose_cover(
        book_id="book-1",
        image_key=image_key,
        title_ar="أرنوب يتعلم المشاركة",
        page_count=24,
        paper_type="color",
        trim_width_in=8.5,
        trim_height_in=8.5,
        storage=storage,
    )

    assert result.jpeg_key == "book-1/cover.jpg"
    assert result.jpeg_key in storage.written_jpegs

    jpeg_bytes = storage.written_jpegs[result.jpeg_key]
    img = Image.open(io.BytesIO(jpeg_bytes))
    assert img.format == "JPEG"
    assert img.mode == "RGB"

    # Front panel only (trim width + one bleed edge, by trim height + two
    # bleed edges), not the full back|spine|front spread -- KDP's Kindle
    # eBook cover spec (config/kdp_rules.json's "ebook_cover") wants just the
    # front artwork, rasterized at EBOOK_COVER_DPI (300).
    expected_width_px = round((8.5 + 0.125) * 300)
    expected_height_px = round((8.5 + 2 * 0.125) * 300)
    assert abs(img.width - expected_width_px) <= 1
    assert abs(img.height - expected_height_px) <= 1

    assert 625 <= img.width <= 10000
    assert 1000 <= img.height <= 10000
    assert len(jpeg_bytes) < 50 * 1024 * 1024


def test_compose_cover_raises_for_unknown_paper_type():
    image_key = "book-1/cover.png"
    storage = FakeStorage({image_key: _make_png_bytes(3000, 2625)})

    try:
        compose_cover(
            book_id="book-1",
            image_key=image_key,
            title_ar="عنوان",
            page_count=24,
            paper_type="glossy-vellum",
            storage=storage,
        )
        assert False, "expected ValueError"
    except ValueError:
        pass
