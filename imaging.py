"""
Shared raster helpers for compose.py's interior PDF path and epub.py's
reflowable EPUB path: downscale an oversized source image and re-encode as
JPEG. JPEG at a high quality setting is visually indistinguishable from a PNG
re-encode for this painterly/photographic AI illustration content, at a
fraction of the size -- PNG's lossless DEFLATE compresses continuous-tone
images poorly. 4:4:4 (no chroma subsampling) avoids color fringing at
illustration edges.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image


def fit_and_encode_jpeg(
    image_bytes: bytes, target_width_px: int, target_height_px: int, quality: int
) -> bytes:
    """Resize + center-crop to exactly target_width_px x target_height_px (a
    server-side equivalent of CSS `object-fit: cover`), for compose.py's
    interior PDF path -- caps an oversized source image down to just KDP's
    print resolution floor before embedding it, since WeasyPrint embeds
    whatever pixel dimensions it's given and an uploaded image well above 300
    DPI (Gemini/manual uploads are often 400+) otherwise bloats the PDF with
    pixels no printer will use."""
    with Image.open(BytesIO(image_bytes)) as img:
        img = img.convert("RGB")
        src_width, src_height = img.size
        scale = max(target_width_px / src_width, target_height_px / src_height)
        scaled_width = round(src_width * scale)
        scaled_height = round(src_height * scale)
        img = img.resize((scaled_width, scaled_height), Image.LANCZOS)
        left = (scaled_width - target_width_px) // 2
        top = (scaled_height - target_height_px) // 2
        img = img.crop((left, top, left + target_width_px, top + target_height_px))
        out = BytesIO()
        img.save(out, format="JPEG", quality=quality, subsampling=0, optimize=True)
        return out.getvalue()


def resize_and_encode_jpeg(image_bytes: bytes, max_dimension_px: int, quality: int) -> bytes:
    """Downscale (never upscale) so the longer side is at most
    max_dimension_px, preserving aspect ratio and the full frame -- no crop.
    For epub.py's reflowable EPUB path: an inline image in document flow
    should show the whole illustration, unlike the interior PDF's full-bleed
    background where object-fit: cover cropping is the point."""
    with Image.open(BytesIO(image_bytes)) as img:
        img = img.convert("RGB")
        src_width, src_height = img.size
        scale = min(1.0, max_dimension_px / max(src_width, src_height))
        if scale < 1.0:
            img = img.resize((round(src_width * scale), round(src_height * scale)), Image.LANCZOS)
        out = BytesIO()
        img.save(out, format="JPEG", quality=quality, subsampling=0, optimize=True)
        return out.getvalue()
