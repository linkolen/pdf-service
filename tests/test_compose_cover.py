import io
import sys
from pathlib import Path

from PIL import Image
import pymupdf

sys.path.insert(0, str(Path(__file__).parent.parent))

from compose import CoverOverlay, compose_cover


def _overlay_en():
    return CoverOverlay(
        brand="KIDS HEAVEN",
        authority="AMERICA'S MOST LOVED ACTIVITY SERIES!",
        title="DINOSAUR ACTIVITY BOOK",
        age="AGES 4-6",
        edition="DINOSAUR EDITION",
        skills=["Counting to 8", "Mazes"],
        starburst="24 PAGES OF THEMED PUZZLES AND ACTIVITIES IN ONE BOOK!",
        comes_head="COMES WITH:",
        comes_with=["Full Answer Key", "Award Certificate"],
    )


def test_compose_cover_overlay_embeds_all_copy():
    image_key = "book-1/cover.png"
    storage = FakeStorage({image_key: _make_png_bytes(3000, 2625)})

    result = compose_cover(
        book_id="book-1",
        image_key=image_key,
        page_count=24,
        paper_type="color",
        language="en",
        storage=storage,
        overlay=_overlay_en(),
    )

    doc = pymupdf.open(stream=storage.written_pdfs[result.pdf_key], filetype="pdf")
    try:
        # Brand uses letter-spacing (extracts as "K I D S ..."), so compare spaceless.
        text = doc[0].get_text().replace(" ", "")
        for needle in ("KIDSHEAVEN", "DINOSAURACTIVITYBOOK", "AGES4-6",
                       "DINOSAUREDITION", "Countingto8", "Mazes",
                       "24PAGES", "FullAnswerKey", "AwardCertificate"):
            assert needle in text, needle
    finally:
        doc.close()


def test_compose_cover_overlay_stays_on_front_panel():
    image_key = "book-1/cover.png"
    storage = FakeStorage({image_key: _make_png_bytes(3000, 2625)})

    result = compose_cover(
        book_id="book-1",
        image_key=image_key,
        page_count=24,
        paper_type="color",
        language="en",
        storage=storage,
        overlay=_overlay_en(),
    )

    doc = pymupdf.open(stream=storage.written_pdfs[result.pdf_key], filetype="pdf")
    try:
        page = doc[0]
        front_width_pt = (8.5 + 0.125) * 72
        front_left = page.rect.width - front_width_pt
        for block in page.get_text("blocks"):
            x0, _, x1, _, text, *_ = block
            if "KIDS HEAVEN" in text or "DINOSAUR" in text or "Mazes" in text:
                assert x0 >= front_left - 1, (text[:30], x0, front_left)
                assert x1 <= page.rect.width + 1, (text[:30], x1)
    finally:
        doc.close()


def test_compose_cover_overlay_arabic_renders():
    image_key = "book-1/cover.png"
    storage = FakeStorage({image_key: _make_png_bytes(3000, 2625)})
    overlay = CoverOverlay(
        brand="KIDS HEAVEN",
        authority="سلسلة كتب الأنشطة الأكثر حباً!",
        title="كتاب الأنشطة: dinosaur",
        age="الأعمار 4-6",
        edition="إصدار dinosaur",
        skills=["المتاهات", "العَدّ حتى ٨"],
        starburst="24 صفحة من الألغاز والأنشطة الممتعة في كتاب واحد!",
        comes_head="يشمل:",
        comes_with=["مفتاح الإجابات الكامل", "شهادة تقدير"],
    )

    result = compose_cover(
        book_id="book-1",
        image_key=image_key,
        page_count=24,
        paper_type="color",
        language="ar",
        storage=storage,
        overlay=overlay,
    )

    doc = pymupdf.open(stream=storage.written_pdfs[result.pdf_key], filetype="pdf")
    try:
        text = doc[0].get_text()
        assert "KIDS" in text.replace(" ", "")
        # Arabic copy must be set in the embedded Naskh face (which shapes
        # natively) -- not in a fallback without Arabic shaping support.
        fonts = {f[3] for f in doc[0].get_fonts(full=True)}
        assert any("Naskh" in name for name in fonts), fonts
        assert any(0x0600 <= ord(ch) <= 0x06FF for ch in text)
        assert "ï¿¿" not in text
    finally:
        doc.close()


def test_compose_cover_overlay_keeps_jpeg_compliant():
    image_key = "book-1/cover.png"
    storage = FakeStorage({image_key: _make_png_bytes(3000, 2625)})

    result = compose_cover(
        book_id="book-1",
        image_key=image_key,
        page_count=24,
        paper_type="color",
        trim_width_in=8.5,
        trim_height_in=8.5,
        language="en",
        storage=storage,
        overlay=_overlay_en(),
    )

    img = Image.open(io.BytesIO(storage.written_jpegs[result.jpeg_key]))
    assert img.format == "JPEG"
    assert img.mode == "RGB"
    assert abs(img.width - round((8.5 + 0.125) * 300)) <= 1
    assert abs(img.height - round((8.5 + 2 * 0.125) * 300)) <= 1


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
        page_count=24,
        paper_type="color",
        storage=storage,
    )

    assert result.pdf_key == "book-1/cover.pdf"
    assert result.pdf_key in storage.written_pdfs
    pdf_bytes = storage.written_pdfs[result.pdf_key]
    assert pdf_bytes[:4] == b"%PDF"

    # The cover carries no overlaid text at all -- the illustration alone
    # fills the wraparound spread.
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        assert doc[0].get_text().strip() == ""
    finally:
        doc.close()


def test_compose_cover_writes_kdp_compliant_ebook_jpeg():
    image_key = "book-1/cover.png"
    storage = FakeStorage({image_key: _make_png_bytes(3000, 2625)})

    result = compose_cover(
        book_id="book-1",
        image_key=image_key,
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
            page_count=24,
            paper_type="glossy-vellum",
            storage=storage,
        )
        assert False, "expected ValueError"
    except ValueError:
        pass
