import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import layout


class TestValidatePageCount:
    def test_at_minimum_is_fine(self):
        assert layout.validate_page_count(24) == []

    def test_at_maximum_is_fine(self):
        assert layout.validate_page_count(828) == []

    def test_typical_count_is_fine(self):
        assert layout.validate_page_count(32) == []

    def test_below_minimum_warns(self):
        warnings = layout.validate_page_count(23)
        assert len(warnings) == 1
        assert "below KDP's minimum of 24" in warnings[0]

    def test_above_maximum_warns(self):
        warnings = layout.validate_page_count(829)
        assert len(warnings) == 1
        assert "exceeds KDP's maximum of 828" in warnings[0]


class TestInsideMarginIn:
    @pytest.mark.parametrize(
        "total_pages,expected_in",
        [
            (24, 0.375),
            (150, 0.375),
            (151, 0.5),
            (300, 0.5),
            (301, 0.625),
            (500, 0.625),
            (501, 0.75),
            (700, 0.75),
            (701, 0.875),
            (828, 0.875),
        ],
    )
    def test_table_boundaries(self, total_pages, expected_in):
        assert layout.inside_margin_in(total_pages) == expected_in

    def test_below_documented_range_clamps_to_smallest_bracket(self):
        assert layout.inside_margin_in(10) == 0.375

    def test_above_documented_range_clamps_to_largest_bracket(self):
        assert layout.inside_margin_in(900) == 0.875


class TestOutsideMarginIn:
    def test_with_bleed(self):
        assert layout.outside_margin_in(bleed=True) == 0.375

    def test_without_bleed(self):
        assert layout.outside_margin_in(bleed=False) == 0.25


class TestGetPageMargins:
    def test_recto_page_has_gutter_on_left(self):
        margins = layout.get_page_margins(page_number=1, total_pages=200)
        assert margins.left_in == 0.5  # inside/gutter for 151-300 bracket
        assert margins.right_in == 0.375  # outside, with bleed
        assert margins.top_in == 0.375
        assert margins.bottom_in == 0.375

    def test_verso_page_has_gutter_on_right(self):
        margins = layout.get_page_margins(page_number=2, total_pages=200)
        assert margins.left_in == 0.375
        assert margins.right_in == 0.5

    def test_odd_even_alternation_across_book(self):
        odd = layout.get_page_margins(5, total_pages=200)
        even = layout.get_page_margins(6, total_pages=200)
        assert odd.left_in == even.right_in
        assert odd.right_in == even.left_in


class TestSpineWidthIn:
    def test_bw_paper(self):
        assert layout.spine_width_in(24, "bw") == pytest.approx(0.0540, abs=1e-4)

    def test_cream_paper(self):
        assert layout.spine_width_in(100, "cream") == pytest.approx(0.25, abs=1e-4)

    def test_color_paper(self):
        assert layout.spine_width_in(24, "color") == pytest.approx(0.0563, abs=1e-4)

    def test_unknown_paper_type_raises(self):
        with pytest.raises(ValueError):
            layout.spine_width_in(100, "glossy-vellum")


class TestCoverDimensions:
    def test_cover_width(self):
        assert layout.cover_width_in(trim_width_in=8.5, bleed_in=0.125, spine_in=0.5) == 17.75

    def test_cover_height(self):
        assert layout.cover_height_in(trim_height_in=8.5, bleed_in=0.125) == 8.75
