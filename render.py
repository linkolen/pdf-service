"""
Milestone 1 (spec Section 9, step 1): standalone proof that this service can
render correct RTL Arabic text over a full-bleed image into a KDP-sized PDF
page, with the font embedded. Everything here is hardcoded on purpose --
no MinIO, no FastAPI, no multi-page merge yet. Run inside the Docker image
(see Dockerfile) since WeasyPrint needs system libs not present on the host.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"

TRIM_WIDTH_IN = 8.5
TRIM_HEIGHT_IN = 8.5
BLEED_IN = 0.125
SAFE_MARGIN_IN = 0.375  # inset from trim edge, keeps text out of the bleed/trim zone

TEXT_AR = (
    "في يومٍ مشمسٍ، خرجت الأرنبة الصغيرة تلعب بين الزهور، "
    "وقالت: يا لها من حديقةٍ جميلة!"
)


def render_page1() -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("page.html")

    page_width_in = TRIM_WIDTH_IN + 2 * BLEED_IN
    page_height_in = TRIM_HEIGHT_IN + 2 * BLEED_IN

    html_str = template.render(
        page_width_in=page_width_in,
        page_height_in=page_height_in,
        safe_margin_in=SAFE_MARGIN_IN,
        safe_zone_width_in=page_width_in - 2 * SAFE_MARGIN_IN,
        safe_zone_height_in=page_height_in - 2 * SAFE_MARGIN_IN,
        image_path="../assets/sample_page.png",
        font_path="../fonts/NotoNaskhArabic[wght].ttf",
        text_ar=TEXT_AR,
    )

    output_path = OUTPUT_DIR / "page1.pdf"
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(str(output_path))
    return output_path


if __name__ == "__main__":
    path = render_page1()
    print(f"Wrote {path}")
