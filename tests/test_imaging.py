import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent.parent))

from imaging import prepare_coloring_page_png


def _png_bytes(size: tuple[int, int], color) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_prepare_coloring_page_png_thresholds_off_white_to_white():
    # Slightly off-white everywhere, like a real AI line-art background --
    # this must end up pure white.
    source = _png_bytes((200, 200), (245, 240, 235))

    out = prepare_coloring_page_png(source, max_width_px=200, max_height_px=200)

    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG"
    assert img.getpixel((190, 190)) == (255, 255, 255)


def test_prepare_coloring_page_png_thresholds_dark_gray_to_black():
    source = _png_bytes((200, 200), (40, 40, 40))

    out = prepare_coloring_page_png(source, max_width_px=200, max_height_px=200)

    img = Image.open(io.BytesIO(out))
    assert img.getpixel((190, 190)) == (0, 0, 0)


def test_prepare_coloring_page_png_forces_saturated_fill_to_white():
    # The image model is asked for black-and-white line art but sometimes
    # ignores that and fills a shape with real, vivid color instead (e.g. a
    # filled blue bicycle wheel). That color can be dark enough on luminance
    # alone to be crushed into a solid black blob; since it's clearly
    # colorful (not colorless ink or background), it must be forced white.
    source = _png_bytes((200, 200), (30, 100, 200))

    out = prepare_coloring_page_png(source, max_width_px=200, max_height_px=200)

    img = Image.open(io.BytesIO(out))
    assert img.getpixel((100, 100)) == (255, 255, 255)

    # Same for a vivid swatch in the top-left corner -- there is no longer a
    # preserved "color reference" region anywhere on the page.
    img2 = Image.new("RGB", (200, 200), (255, 255, 255))
    ImageDraw.Draw(img2).rectangle([0, 0, 40, 40], fill=(220, 30, 30))
    buf = io.BytesIO()
    img2.save(buf, format="PNG")
    out2 = prepare_coloring_page_png(buf.getvalue(), max_width_px=200, max_height_px=200)
    result = Image.open(io.BytesIO(out2))
    assert result.getpixel((10, 10)) == (255, 255, 255)
    assert result.getpixel((190, 190)) == (255, 255, 255)


def test_prepare_coloring_page_png_still_blackens_desaturated_midtone():
    # A plain mid-gray dark enough to pass the strong threshold on its own
    # (no adjacency to a strong pixel needed) is real "ink-like" content and
    # should stay black -- only saturated color gets the white-instead-of-
    # black treatment above.
    source = _png_bytes((200, 200), (90, 90, 90))

    out = prepare_coloring_page_png(source, max_width_px=200, max_height_px=200)

    img = Image.open(io.BytesIO(out))
    assert img.getpixel((190, 190)) == (0, 0, 0)


def test_prepare_coloring_page_png_keeps_dark_tinted_ink_black():
    # Real failure this file shipped with: the image model's "black" line art
    # often comes back slightly tinted (dark olive/green strokes from soft
    # upscaled sources), and ratio-based HSV saturation flags those pixels
    # (even near-black rgb(5,5,4)) as "colored". Gating on saturation alone
    # punched white pinholes through every stroke; only saturated-AND-bright
    # pixels (real color fills, which have a bright dominant channel) may be
    # forced white -- dark tinted ink must stay solid black.
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 180, 180], fill=(63, 84, 56))
    draw.point((190, 190), fill=(5, 5, 4))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    out = prepare_coloring_page_png(buf.getvalue(), max_width_px=200, max_height_px=200)

    result = Image.open(io.BytesIO(out))
    assert result.getpixel((100, 100)) == (0, 0, 0)
    assert result.getpixel((190, 190)) == (0, 0, 0)


def test_prepare_coloring_page_png_stays_pure_bw_after_downscale():
    # Threshold-before-resize used to LANCZOS-blur the hard black/white mask
    # into mid-gray on its way down to display size, printing as faded lines.
    # Downscaling now happens BEFORE thresholding, so every pixel must come
    # out exactly black or white.
    img = Image.new("RGB", (4000, 2000), (250, 250, 250))
    ImageDraw.Draw(img).ellipse([500, 300, 3500, 1700], outline=(20, 20, 20), width=12)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    out = prepare_coloring_page_png(buf.getvalue(), max_width_px=2400, max_height_px=2363)

    result = Image.open(io.BytesIO(out)).convert("L")
    for y in range(0, result.height, 7):
        for x in range(0, result.width, 7):
            assert result.getpixel((x, y)) in (0, 255), f"gray pixel at ({x}, {y})"


def test_prepare_coloring_page_png_bridges_anti_aliased_edge_next_to_strong_ink():
    # A strong (near-black) stroke with a lighter, desaturated anti-aliased
    # halo right next to it (within the default 2px hysteresis reach) -- e.g.
    # a soft edge -- must resolve to solid black, not be left white just
    # because it's above the strong threshold on its own.
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([80, 0, 119, 199], fill=(20, 20, 20))  # strong core
    draw.rectangle([120, 0, 121, 199], fill=(190, 190, 190))  # weak halo, touching the core
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    out = prepare_coloring_page_png(buf.getvalue(), max_width_px=200, max_height_px=200)

    result = Image.open(io.BytesIO(out))
    assert result.getpixel((121, 100)) == (0, 0, 0)


def test_prepare_coloring_page_png_leaves_isolated_weak_shading_white():
    # A weak (mid-tone, desaturated) region with no strong ink pixel
    # anywhere nearby -- e.g. a soft gradient/shading fill the AI drew
    # instead of leaving the background flat white -- must NOT get pulled
    # in just because it passes the loose luminance cut on its own.
    source = _png_bytes((200, 200), (190, 190, 190))

    out = prepare_coloring_page_png(source, max_width_px=200, max_height_px=200)

    img = Image.open(io.BytesIO(out))
    assert img.getpixel((190, 190)) == (255, 255, 255)


def test_prepare_coloring_page_png_downscales_to_fit_without_cropping():
    source = _png_bytes((4000, 2000), (255, 255, 255))

    out = prepare_coloring_page_png(source, max_width_px=1000, max_height_px=1000)

    img = Image.open(io.BytesIO(out))
    # Contain, not cover: aspect ratio preserved, both dimensions within bounds.
    assert img.width <= 1000
    assert img.height <= 1000
    assert round(img.width / img.height, 2) == round(4000 / 2000, 2)


def test_prepare_coloring_page_png_never_upscales():
    source = _png_bytes((200, 150), (255, 255, 255))

    out = prepare_coloring_page_png(source, max_width_px=2000, max_height_px=2000)

    img = Image.open(io.BytesIO(out))
    assert img.size == (200, 150)
