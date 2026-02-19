"""Tests for postprocess utilities."""

from services.writing.postprocess import strip_emdashes, postprocess


class TestStripEmdashes:
    def test_emdash_replaced_with_comma(self):
        text = "impressive\u2014especially the scale"
        result = strip_emdashes(text)
        assert result == "impressive, especially the scale"

    def test_emdash_with_spaces_no_double_space(self):
        text = "impressive \u2014 especially the scale"
        result = strip_emdashes(text)
        assert result == "impressive, especially the scale"

    def test_en_dash_replaced(self):
        text = "growth\u2013driven strategy"
        result = strip_emdashes(text)
        assert result == "growth, driven strategy"

    def test_postprocess_includes_emdash_fix(self):
        text = "**bold** and dash\u2014here"
        result = postprocess(text)
        assert result == "bold and dash, here"
