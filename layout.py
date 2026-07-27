"""
KDP interior/cover layout rules (spec Section 6): margin table, spine width
formula, and page-count checks. Numbers are loaded from config/kdp_rules.json
so both this service and (later) the Java service can share one source of
truth instead of each hardcoding their own copy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config" / "kdp_rules.json"


def load_rules() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


_RULES = load_rules()

MIN_PAGE_COUNT: int = _RULES["page_count"]["min"]
MAX_PAGE_COUNT: int = _RULES["page_count"]["max"]


@dataclass(frozen=True)
class PageMargins:
    top_in: float
    bottom_in: float
    left_in: float
    right_in: float


def validate_page_count(total_pages: int) -> list[str]:
    warnings = []
    if total_pages < MIN_PAGE_COUNT:
        warnings.append(
            f"Page count {total_pages} is below KDP's minimum of {MIN_PAGE_COUNT}."
        )
    if total_pages > MAX_PAGE_COUNT:
        warnings.append(
            f"Page count {total_pages} exceeds KDP's maximum of {MAX_PAGE_COUNT}."
        )
    return warnings


def inside_margin_in(total_pages: int) -> float:
    """Gutter margin for the given interior page count, per KDP's table.
    Page counts outside the documented 24-828 range clamp to the nearest
    documented bracket rather than raising -- validate_page_count is what
    surfaces the out-of-range warning."""
    table = _RULES["margins"]["inside_gutter_table_in"]
    for row in table:
        if row["min_pages"] <= total_pages <= row["max_pages"]:
            return row["inside_in"]
    if total_pages < table[0]["min_pages"]:
        return table[0]["inside_in"]
    return table[-1]["inside_in"]


def outside_margin_in(bleed: bool = True) -> float:
    key = "with_bleed" if bleed else "no_bleed"
    return _RULES["margins"]["outside_top_bottom_in"][key]


def get_page_margins(page_number: int, total_pages: int, bleed: bool = True) -> PageMargins:
    """Physical safe-zone margins for one interior page.

    Page 1 is a recto (right-hand) page, so odd page numbers are recto
    (gutter/inside margin on the left) and even numbers are verso
    (gutter/inside margin on the right) -- standard book-binding convention,
    independent of the text's reading direction.
    """
    inside = inside_margin_in(total_pages)
    outside = outside_margin_in(bleed)
    is_recto = page_number % 2 == 1
    left = inside if is_recto else outside
    right = outside if is_recto else inside
    return PageMargins(top_in=outside, bottom_in=outside, left_in=left, right_in=right)


def spine_width_in(total_pages: int, paper_type: str) -> float:
    factors = _RULES["spine_width_factor_in_per_page"]
    if paper_type not in factors:
        raise ValueError(f"Unknown paper_type {paper_type!r}; expected one of {sorted(factors)}")
    return round(total_pages * factors[paper_type], 4)


def cover_width_in(trim_width_in: float, bleed_in: float, spine_in: float) -> float:
    """(2 x (trim width + bleed)) + spine width -- back + spine + front."""
    return round(2 * (trim_width_in + bleed_in) + spine_in, 4)


def cover_height_in(trim_height_in: float, bleed_in: float) -> float:
    return round(trim_height_in + 2 * bleed_in, 4)
