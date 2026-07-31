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

    def get_image_bytes(self, key: str) -> bytes:
        return self._images[key]

    def put_pdf_bytes(self, key: str, data: bytes) -> str:
        self.written_pdfs[key] = data
        return key


def _make_png_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), (180, 90, 40))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_compose_cover_writes_correctly_sized_pdf():
    image_key = "book-1/cover.png"
    storage = FakeStorage({image_key: _make_png_bytes(3000, 2625)})

    output_key = compose_cover(
        book_id="book-1",
        image_key=image_key,
        title_ar="أرنوب يتعلم المشاركة",
        page_count=24,
        paper_type="color",
        storage=storage,
    )

    assert output_key == "book-1/cover.pdf"
    assert output_key in storage.written_pdfs
    assert storage.written_pdfs[output_key][:4] == b"%PDF"


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
