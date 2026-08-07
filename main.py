"""
FastAPI /compose endpoint (spec Section 9, steps 4 and 6): the HTTP surface
Spring Boot calls to turn stored MinIO images into composed PDFs. One
endpoint handles both the interior ("type": "interior") and the wraparound
cover ("type": "cover"), matching the request shape from spec Section 4.3.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from compose import PageSpec, compose_cover, compose_interior

app = FastAPI(title="Arabic Kids Book - PDF Composition Service")


class TrimIn(BaseModel):
    width_in: float = 8.5
    height_in: float = 8.5
    bleed_in: float = 0.125


class PageIn(BaseModel):
    page_number: int
    image_key: str
    text_ar: str


class ComposeRequest(BaseModel):
    book_id: str
    trim: TrimIn = TrimIn()
    type: str = "interior"

    # "interior" fields
    pages: List[PageIn] = []

    # "cover" fields
    image_key: Optional[str] = None
    title_ar: Optional[str] = None
    page_count: Optional[int] = None
    paper_type: Optional[str] = None


class ComposeResponse(BaseModel):
    output_key: str
    epub_output_key: Optional[str] = None
    jpeg_output_key: Optional[str] = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/compose", response_model=ComposeResponse)
def compose(request: ComposeRequest) -> ComposeResponse:
    if request.type == "interior":
        return _compose_interior(request)
    if request.type == "cover":
        return _compose_cover(request)
    raise HTTPException(status_code=400, detail=f"Unsupported compose type: {request.type!r}")


def _compose_interior(request: ComposeRequest) -> ComposeResponse:
    if not request.pages:
        raise HTTPException(status_code=400, detail="At least one page is required")

    pages = [
        PageSpec(page_number=p.page_number, image_key=p.image_key, text_ar=p.text_ar)
        for p in request.pages
    ]

    try:
        result = compose_interior(
            book_id=request.book_id,
            pages=pages,
            trim_width_in=request.trim.width_in,
            trim_height_in=request.trim.height_in,
            bleed_in=request.trim.bleed_in,
            title_ar=request.title_ar,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return ComposeResponse(output_key=result.pdf_key, epub_output_key=result.epub_key)


def _compose_cover(request: ComposeRequest) -> ComposeResponse:
    missing = [
        field
        for field, value in [
            ("image_key", request.image_key),
            ("title_ar", request.title_ar),
            ("page_count", request.page_count),
            ("paper_type", request.paper_type),
        ]
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=400, detail=f"Missing required field(s) for cover compose: {missing}"
        )

    try:
        result = compose_cover(
            book_id=request.book_id,
            image_key=request.image_key,
            title_ar=request.title_ar,
            page_count=request.page_count,
            paper_type=request.paper_type,
            trim_width_in=request.trim.width_in,
            trim_height_in=request.trim.height_in,
            bleed_in=request.trim.bleed_in,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return ComposeResponse(output_key=result.pdf_key, jpeg_output_key=result.jpeg_key)
