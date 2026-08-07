import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

import main
from compose import ComposeCoverResult, ComposeInteriorResult

client = TestClient(main.app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_compose_calls_compose_interior_with_parsed_pages(monkeypatch):
    captured = {}

    def fake_compose_interior(
        book_id, pages, trim_width_in, trim_height_in, bleed_in, title_ar=None, storage=None
    ):
        captured["book_id"] = book_id
        captured["pages"] = pages
        captured["trim"] = (trim_width_in, trim_height_in, bleed_in)
        return ComposeInteriorResult(
            pdf_key=f"{book_id}/interior.pdf", epub_key=f"{book_id}/interior.epub"
        )

    monkeypatch.setattr(main, "compose_interior", fake_compose_interior)

    response = client.post(
        "/compose",
        json={
            "book_id": "book-1",
            "trim": {"width_in": 8.5, "height_in": 8.5, "bleed_in": 0.125},
            "pages": [
                {"page_number": 1, "image_key": "book-1/page-1.png", "text_ar": "نص"}
            ],
            "type": "interior",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "output_key": "book-1/interior.pdf",
        "epub_output_key": "book-1/interior.epub",
        "jpeg_output_key": None,
    }
    assert captured["book_id"] == "book-1"
    assert captured["trim"] == (8.5, 8.5, 0.125)
    assert len(captured["pages"]) == 1
    assert captured["pages"][0].page_number == 1
    assert captured["pages"][0].image_key == "book-1/page-1.png"


def test_compose_uses_default_trim_when_omitted(monkeypatch):
    captured = {}

    def fake_compose_interior(
        book_id, pages, trim_width_in, trim_height_in, bleed_in, title_ar=None, storage=None
    ):
        captured["trim"] = (trim_width_in, trim_height_in, bleed_in)
        return ComposeInteriorResult(pdf_key="out.pdf", epub_key="out.epub")

    monkeypatch.setattr(main, "compose_interior", fake_compose_interior)

    response = client.post(
        "/compose",
        json={
            "book_id": "book-1",
            "pages": [{"page_number": 1, "image_key": "k", "text_ar": "t"}],
        },
    )

    assert response.status_code == 200
    assert captured["trim"] == (8.5, 8.5, 0.125)


def test_compose_rejects_empty_pages():
    response = client.post("/compose", json={"book_id": "book-1", "pages": []})
    assert response.status_code == 400


def test_compose_rejects_unsupported_type():
    response = client.post(
        "/compose",
        json={
            "book_id": "book-1",
            "pages": [{"page_number": 1, "image_key": "k", "text_ar": "t"}],
            "type": "audiobook",
        },
    )
    assert response.status_code == 400


def test_compose_wraps_internal_errors_as_500(monkeypatch):
    def raise_error(*args, **kwargs):
        raise RuntimeError("minio unreachable")

    monkeypatch.setattr(main, "compose_interior", raise_error)

    response = client.post(
        "/compose",
        json={
            "book_id": "book-1",
            "pages": [{"page_number": 1, "image_key": "k", "text_ar": "t"}],
        },
    )

    assert response.status_code == 500
    assert "minio unreachable" in response.json()["detail"]


def test_compose_cover_calls_compose_cover_with_parsed_fields(monkeypatch):
    captured = {}

    def fake_compose_cover(book_id, image_key, title_ar, page_count, paper_type,
                           trim_width_in, trim_height_in, bleed_in, storage=None):
        captured.update(locals())
        return ComposeCoverResult(pdf_key=f"{book_id}/cover.pdf", jpeg_key=f"{book_id}/cover.jpg")

    monkeypatch.setattr(main, "compose_cover", fake_compose_cover)

    response = client.post(
        "/compose",
        json={
            "book_id": "book-1",
            "type": "cover",
            "image_key": "book-1/cover.png",
            "title_ar": "عنوان الكتاب",
            "page_count": 24,
            "paper_type": "color",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "output_key": "book-1/cover.pdf",
        "epub_output_key": None,
        "jpeg_output_key": "book-1/cover.jpg",
    }
    assert captured["book_id"] == "book-1"
    assert captured["image_key"] == "book-1/cover.png"
    assert captured["title_ar"] == "عنوان الكتاب"
    assert captured["page_count"] == 24
    assert captured["paper_type"] == "color"
    assert captured["trim_width_in"] == 8.5


def test_compose_cover_rejects_missing_fields():
    response = client.post(
        "/compose",
        json={"book_id": "book-1", "type": "cover", "image_key": "book-1/cover.png"},
    )
    assert response.status_code == 400
    assert "title_ar" in response.json()["detail"]


def test_compose_cover_wraps_internal_errors_as_500(monkeypatch):
    def raise_error(*args, **kwargs):
        raise ValueError("unknown paper_type")

    monkeypatch.setattr(main, "compose_cover", raise_error)

    response = client.post(
        "/compose",
        json={
            "book_id": "book-1",
            "type": "cover",
            "image_key": "book-1/cover.png",
            "title_ar": "عنوان",
            "page_count": 24,
            "paper_type": "glossy-vellum",
        },
    )

    assert response.status_code == 500
    assert "unknown paper_type" in response.json()["detail"]
