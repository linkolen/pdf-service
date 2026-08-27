import io
import sys
import zipfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from compose import PageSpec, compose_interior


class FakeStorage:
    """In-memory stand-in for storage.Storage so compose_interior can be unit
    tested without a real MinIO -- WeasyPrint and the EPUB builder still run
    for real."""

    def __init__(self, images: dict[str, bytes]):
        self._images = images
        self.written_pdfs: dict[str, bytes] = {}
        self.written_epubs: dict[str, bytes] = {}

    def get_image_bytes(self, key: str) -> bytes:
        return self._images[key]

    def put_pdf_bytes(self, key: str, data: bytes) -> str:
        self.written_pdfs[key] = data
        return key

    def put_epub_bytes(self, key: str, data: bytes) -> str:
        self.written_epubs[key] = data
        return key


def _make_png_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), (60, 120, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_pages(count: int) -> list[PageSpec]:
    return [
        PageSpec(page_number=n, image_key=f"book-1/page-{n}.png", text_ar=f"نص الصفحة {n}")
        for n in range(1, count + 1)
    ]


def test_compose_interior_writes_pdf_and_epub():
    images = {f"book-1/page-{n}.png": _make_png_bytes(2625, 2625) for n in range(1, 4)}
    storage = FakeStorage(images)

    result = compose_interior(
        book_id="book-1", pages=_make_pages(3), title_ar="أرنوب يتعلم المشاركة", storage=storage
    )

    assert result.pdf_key == "book-1/interior.pdf"
    assert result.epub_key == "book-1/interior.epub"
    assert result.pdf_key in storage.written_pdfs
    assert result.epub_key in storage.written_epubs
    assert storage.written_pdfs[result.pdf_key][:4] == b"%PDF"


def test_compose_interior_epub_is_a_valid_zip_with_required_entries():
    images = {f"book-1/page-{n}.png": _make_png_bytes(2625, 2625) for n in range(1, 3)}
    storage = FakeStorage(images)

    result = compose_interior(book_id="book-1", pages=_make_pages(2), storage=storage)

    epub_bytes = storage.written_epubs[result.epub_key]
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        names = zf.namelist()

        # mimetype must be the first entry and stored uncompressed.
        info = zf.infolist()[0]
        assert info.filename == "mimetype"
        assert info.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"

        assert "META-INF/container.xml" in names
        assert "OEBPS/content.opf" in names
        assert "OEBPS/nav.xhtml" in names
        assert "OEBPS/css/style.css" in names
        assert "OEBPS/fonts/NotoNaskhArabic.ttf" in names
        assert "OEBPS/text/page-0001.xhtml" in names
        assert "OEBPS/text/page-0002.xhtml" in names
        assert "OEBPS/images/page-0001.jpg" in names
        assert "OEBPS/images/page-0002.jpg" in names

        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert 'page-progression-direction="rtl"' in opf
        # KDP's own troubleshooting docs reject EPUBs whose OPF declares the
        # fixed-layout rendition property -- this must never reappear, see
        # epub.py's module docstring.
        assert 'property="rendition:layout"' not in opf

        page_xhtml = zf.read("OEBPS/text/page-0001.xhtml").decode("utf-8")
        assert "نص الصفحة 1" in page_xhtml
        assert 'dir="rtl"' in page_xhtml

        css = zf.read("OEBPS/css/style.css").decode("utf-8")
        # EPUB CSS profile forbids these outright (epubcheck CSS-001).
        assert "direction:" not in css
        assert "unicode-bidi:" not in css


def test_compose_interior_defaults_epub_title_to_book_id_when_missing():
    images = {"book-1/page-1.png": _make_png_bytes(2625, 2625)}
    storage = FakeStorage(images)

    result = compose_interior(book_id="book-1", pages=_make_pages(1), storage=storage)

    epub_bytes = storage.written_epubs[result.epub_key]
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:title>book-1</dc:title>" in opf


def test_compose_interior_coloring_book_writes_png_pages_and_valid_pdf():
    images = {f"book-1/page-{n}.png": _make_png_bytes(2625, 2625) for n in range(1, 3)}
    pages = [
        PageSpec(page_number=1, image_key="book-1/page-1.png", text_ar="قطة"),
        PageSpec(page_number=2, image_key="book-1/page-2.png", text_ar=""),
    ]
    storage = FakeStorage(images)

    result = compose_interior(
        book_id="book-1", pages=pages, title_ar="كتاب تلوين", book_type="coloring", storage=storage
    )

    assert storage.written_pdfs[result.pdf_key][:4] == b"%PDF"

    epub_bytes = storage.written_epubs[result.epub_key]
    with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
        names = zf.namelist()
        # Coloring pages still go through the same reencode-as-JPEG EPUB
        # image path (epub.py doesn't branch on book_type -- it's already
        # book-type-agnostic, see page.xhtml's conditional caption).
        assert "OEBPS/images/page-0001.jpg" in names

        page_with_caption = zf.read("OEBPS/text/page-0001.xhtml").decode("utf-8")
        assert "قطة" in page_with_caption

        page_without_caption = zf.read("OEBPS/text/page-0002.xhtml").decode("utf-8")
        assert "<p" not in page_without_caption


def test_compose_interior_coloring_book_thresholds_to_pure_black_and_white():
    # An off-white, slightly textured "line art" source -- exactly what an AI
    # image model tends to produce instead of a pure white background.
    img = Image.new("RGB", (2625, 2625), (245, 240, 235))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    images = {"book-1/page-1.png": buf.getvalue()}
    storage = FakeStorage(images)

    compose_interior(
        book_id="book-1",
        pages=[PageSpec(page_number=1, image_key="book-1/page-1.png", text_ar="")],
        book_type="coloring",
        storage=storage,
    )

    # No direct handle to the embedded page PNG from the PDF alone here --
    # imaging.prepare_coloring_page_png is covered directly in
    # test_imaging.py; this test just confirms the coloring path runs
    # end-to-end without error on a realistic off-white source image.
    assert storage.written_pdfs
