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
from typing import Optional

from PIL import Image, ImageChops, ImageFilter


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


def _otsu_threshold(histogram: list) -> Optional[int]:
    """Midpoint of the two class means at Otsu's optimal split over a 256-bin
    PIL histogram -- not the raw split index. On cleanly separated art (a
    compact dark-ink cluster vs. a large white-background cluster) every
    split between the two clusters maximizes the same inter-class variance,
    so the raw index can land ON the ink cluster's own value; the
    mean-midpoint always sits safely between the classes. Returns None when
    the histogram is degenerate (one class only -- e.g. a uniformly white or
    uniformly gray test image): with no background/ink split to find, a
    fixed default pair of cutoffs is the honest fallback."""
    total = sum(histogram)
    sum_all = sum(i * count for i, count in enumerate(histogram))
    sum_background = 0.0
    weight_background = 0
    best_t = None
    best_variance = -1.0
    for t in range(256):
        weight_background += histogram[t]
        if weight_background == 0:
            continue
        weight_foreground = total - weight_background
        if weight_foreground == 0:
            break
        sum_background += t * histogram[t]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_all - sum_background) / weight_foreground
        variance = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2
        if variance > best_variance:
            best_variance = variance
            best_t = t
    if best_t is None or best_variance <= 0:
        return None
    sum_background -= best_t * histogram[best_t]
    weight_background -= histogram[best_t]
    if weight_background == 0 or weight_background == total:
        return None
    mean_background = sum_background / weight_background
    mean_foreground = (sum_all - sum_background) / (total - weight_background)
    return round((mean_background + mean_foreground) / 2)


def prepare_coloring_page_png(
    image_bytes: bytes,
    max_width_px: int,
    max_height_px: int,
    weak_threshold: Optional[int] = None,
    strong_threshold: Optional[int] = None,
    saturation_threshold: int = 50,
    saturation_brightness_floor: int = 110,
    hysteresis_iterations: int = 2,
) -> bytes:
    """Threshold the whole page to pure black-on-white line art. Downscale
    (never upscale, no crop) to fit within max_width_px x max_height_px.

    Order matters: the source is downscaled FIRST, then thresholded. The
    previous order (threshold at source resolution, then LANCZOS-resize)
    re-blurred every hard black/white edge into mid-gray during the resize,
    so printed lines looked faded; thresholding last means every pixel is
    exactly #000 or #FFF in the embedded PNG. LANCZOS on the continuous-tone
    source is fine -- it's the input to a threshold, not the output.

    Uses a Canny-style hysteresis threshold rather than one flat cut, on
    both a luminance and an HSV-saturation channel:

    - "strong" ink: luminance <= strong_threshold AND NOT saturated-bright
      -- pixels dark enough to be confidently real ink, always kept.
    - "weak" candidates: luminance <= weak_threshold AND NOT saturated-bright
      -- a much more generous net that also catches anti-aliased stroke
      edges and soft shading, but is ambiguous on its own.
    - A weak pixel only becomes ink if it is within hysteresis_iterations
      pixels of a strong pixel (grown via repeated 3x3 dilation, clipped to
      the weak mask each step). This bridges genuine anti-aliasing right
      around a real stroke without flood-filling large, separate mid-tone
      regions the AI shaded instead of leaving flat white -- those stay
      white since they're not adjacent to a strong core.
    - A final morphological closing (dilate then erode) fills residual
      pinholes inside strokes before they print as speckle.

    Both luminance cutoffs derive from Otsu's threshold computed over the
    whole page's luminance histogram, falling back to the previous fixed
    115/210 when Otsu finds no two-class split. Fixed cutoffs were brittle
    across art styles: soft upscaled strokes whose cores never reach a
    strict cutoff lose their seeds and erode away entirely, leaving thin
    broken lines.

    The saturation gate only kills pixels that are BOTH saturated AND bright
    (max RGB channel >= saturation_brightness_floor). Gating on saturation
    alone punched holes through genuinely dark, slightly-tinted ink --
    dark-olive stroke pixels like rgb(63, 84, 56), and even near-black
    rgb(5, 5, 4), whose ratio-based HSV "saturation" is inflated by a
    near-zero max channel -- speckling every line. Real leaked color fills
    (a red wheel, a blue sky patch) have a bright dominant channel and are
    still forced white; dark tinted ink is kept as ink.

    Coloring pages lay out with a white margin/border rather than the
    storybook's full-bleed cover-fit, so the whole subject must stay visible
    -- hence "fit within", not fit_and_encode_jpeg's crop-to-cover. PNG, not
    JPEG: line art is flat black-on-white, exactly what PNG's lossless
    DEFLATE compresses smallest, and JPEG's block artifacts would introduce
    gray fringing around the hard edges thresholding just produced, undoing
    the point of it."""
    with Image.open(BytesIO(image_bytes)) as img:
        img = img.convert("RGB")
        src_width, src_height = img.size

        scale = min(1.0, max_width_px / src_width, max_height_px / src_height)
        if scale < 1.0:
            img = img.resize((round(src_width * scale), round(src_height * scale)), Image.LANCZOS)

        luminance = img.convert("L")

        otsu = _otsu_threshold(luminance.histogram())
        resolved_weak = weak_threshold if weak_threshold is not None else (
            min(235, otsu + 68) if otsu is not None else 210
        )
        resolved_strong = strong_threshold if strong_threshold is not None else (
            max(48, otsu - 27) if otsu is not None else 115
        )
        saturation = img.convert("HSV").split()[1]
        red, green, blue = img.split()
        brightness = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        saturated = saturation.point(lambda p: 255 if p > saturation_threshold else 0)
        bright = brightness.point(lambda p: 255 if p >= saturation_brightness_floor else 0)
        color_kill = ImageChops.darker(saturated, bright)
        keep_candidate = color_kill.point(lambda p: 0 if p >= 128 else 255)

        weak_dark = luminance.point(lambda p: 255 if p <= resolved_weak else 0)
        weak_ink = ImageChops.darker(weak_dark, keep_candidate)

        strong_dark = luminance.point(lambda p: 255 if p <= resolved_strong else 0)
        ink_mask = ImageChops.darker(strong_dark, keep_candidate)
        for _ in range(hysteresis_iterations):
            grown = ink_mask.filter(ImageFilter.MaxFilter(3))
            ink_mask = ImageChops.darker(grown, weak_ink)

        closed = ink_mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
        ink_mask = ImageChops.darker(closed, ink_mask)

        thresholded = ink_mask.point(lambda p: 0 if p >= 128 else 255).convert("RGB")

        out = BytesIO()
        thresholded.save(out, format="PNG", optimize=True)
        return out.getvalue()
