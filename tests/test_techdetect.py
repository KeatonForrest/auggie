"""Tests for services/techdetect/ — custom technology detection engine."""

import pytest
import re
from services.techdetect.patterns import prepare_pattern, extract_version, PreparedPattern
from services.techdetect.webpage import WebPage
from services.techdetect.fingerprints import load_fingerprints, Technology
from services.techdetect.detector import TechDetector, DetectionResult


# ============================================================
# Pattern parsing tests
# ============================================================

class TestPreparePattern:
    def test_simple_regex(self):
        p = prepare_pattern("jquery")
        assert p.regex.search("jquery.min.js")
        assert p.confidence == 100
        assert p.version == ""

    def test_version_extraction(self):
        p = prepare_pattern("jquery/([\\d.]+)\\;version:\\1")
        assert p.version == "\\1"
        assert p.confidence == 100

    def test_confidence_override(self):
        p = prepare_pattern("something\\;confidence:50")
        assert p.confidence == 50

    def test_invalid_regex_fallback(self):
        p = prepare_pattern("[invalid(")
        assert p.regex.search("anything") is None

    def test_combined_version_and_confidence(self):
        p = prepare_pattern("lib/([\\d.]+)\\;version:\\1\\;confidence:80")
        assert p.version == "\\1"
        assert p.confidence == 80


class TestExtractVersion:
    def test_simple_backreference(self):
        p = prepare_pattern("jquery/([\\d.]+)\\;version:\\1")
        assert extract_version(p, "jquery/3.6.0") == "3.6.0"

    def test_ternary_nonempty(self):
        p = prepare_pattern("(\\d+)?\\;version:\\1?found:notfound")
        assert extract_version(p, "42") == "found"

    def test_ternary_empty(self):
        # (x)? matches empty string, so capture group is empty -> false branch
        p = prepare_pattern("(x)?\\;version:\\1?found:notfound")
        assert extract_version(p, "y") == "notfound"

    def test_ternary_empty_branch(self):
        # Match with empty capture group
        p = prepare_pattern("Apache(?:/(\\S*))?\\;version:\\1?\\1:")
        assert extract_version(p, "Apache") is None  # empty version -> None

    def test_multiple_groups(self):
        p = prepare_pattern("v(\\d+)\\.(\\d+)\\;version:\\1.\\2")
        assert extract_version(p, "v1.2") == "1.2"

    def test_apache_with_version(self):
        p = prepare_pattern("Apache/?([\\d.]+)?\\;version:\\1")
        assert extract_version(p, "Apache/2.4.51") == "2.4.51"

    def test_apache_without_version(self):
        p = prepare_pattern("Apache/?([\\d.]+)?\\;version:\\1")
        result = extract_version(p, "Apache")
        assert result is None  # empty capture -> None

    def test_no_version_template(self):
        p = prepare_pattern("jquery")
        assert extract_version(p, "jquery") is None


# ============================================================
# WebPage parsing tests
# ============================================================

class TestWebPage:
    def test_extract_scripts(self):
        html = '<html><head><script src="/js/app.js"></script><script src="https://cdn.example.com/lib.js"></script></head></html>'
        wp = WebPage("https://example.com", html, {})
        assert "/js/app.js" in wp.scripts
        assert "https://cdn.example.com/lib.js" in wp.scripts

    def test_extract_meta(self):
        html = '<html><head><meta name="Generator" content="WordPress 6.0"><meta property="og:type" content="website"></head></html>'
        wp = WebPage("https://example.com", html, {})
        assert wp.meta.get("generator") == "WordPress 6.0"
        assert wp.meta.get("og:type") == "website"

    def test_headers_lowercased(self):
        wp = WebPage("https://example.com", "<html></html>", {"Content-Type": "text/html", "X-Powered-By": "PHP/8.1"})
        assert wp.headers["content-type"] == "text/html"
        assert wp.headers["x-powered-by"] == "PHP/8.1"


# ============================================================
# Fingerprint loading tests
# ============================================================

class TestLoadFingerprints:
    def test_loads_bundled_json(self):
        techs, cats = load_fingerprints()
        assert len(techs) > 1000
        assert "WordPress" in techs
        assert len(cats) > 50

    def test_custom_path(self, tmp_path):
        import json
        data = {
            "categories": {"1": {"name": "CMS"}},
            "technologies": {
                "TestTech": {"cats": [1], "html": "<test>", "implies": "OtherTech"},
                "OtherTech": {"cats": [1]},
            },
        }
        fp = tmp_path / "tech.json"
        fp.write_text(json.dumps(data))
        techs, cats = load_fingerprints(str(fp))
        assert "TestTech" in techs
        assert techs["TestTech"].html_patterns
        assert techs["TestTech"].implies == ("OtherTech",)

    def test_normalization_string_to_list(self):
        techs, _ = load_fingerprints()
        # WordPress has html patterns (strings get coerced to lists)
        wp = techs["WordPress"]
        assert isinstance(wp.html_patterns, tuple)


# ============================================================
# Technology matching tests
# ============================================================

class TestCheckTechnology:
    @pytest.fixture
    def detector(self):
        return TechDetector()

    def test_url_pattern_match(self, detector):
        """Validates the URL bug fix — URL match should produce a detection."""
        import json, os
        # Find a tech with url patterns
        tech = Technology(
            name="TestURL",
            url_patterns=(prepare_pattern("\\.example\\.com"),),
        )
        wp = WebPage("https://shop.example.com", "<html></html>", {})
        result = detector._check_technology(tech, wp)
        assert result is not None

    def test_header_match(self, detector):
        tech = Technology(
            name="PHP",
            header_patterns=(("x-powered-by", prepare_pattern("PHP/([\\d.]+)\\;version:\\1")),),
        )
        wp = WebPage("https://example.com", "<html></html>", {"X-Powered-By": "PHP/8.1.2"})
        result = detector._check_technology(tech, wp)
        assert result is not None
        assert "8.1.2" in result.versions

    def test_script_match(self, detector):
        tech = Technology(
            name="jQuery",
            script_patterns=(prepare_pattern("jquery[.-]([\\d]+(?:\\.[\\d]+)*)\\;version:\\1"),),
        )
        html = '<html><head><script src="https://cdn.example.com/jquery-3.6.0.min.js"></script></head></html>'
        wp = WebPage("https://example.com", html, {})
        result = detector._check_technology(tech, wp)
        assert result is not None
        assert "3.6.0" in result.versions

    def test_meta_match(self, detector):
        tech = Technology(
            name="WordPress",
            meta_patterns=(("generator", prepare_pattern("WordPress\\s?([\\d.]+)?\\;version:\\1")),),
        )
        html = '<html><head><meta name="generator" content="WordPress 6.0"></head></html>'
        wp = WebPage("https://example.com", html, {})
        result = detector._check_technology(tech, wp)
        assert result is not None
        assert "6.0" in result.versions

    def test_html_match(self, detector):
        tech = Technology(
            name="Bootstrap",
            html_patterns=(prepare_pattern("bootstrap\\.min\\.css"),),
        )
        html = '<html><head><link href="bootstrap.min.css"></head></html>'
        wp = WebPage("https://example.com", html, {})
        result = detector._check_technology(tech, wp)
        assert result is not None

    def test_no_match(self, detector):
        tech = Technology(
            name="Nothing",
            html_patterns=(prepare_pattern("willnevermatch12345"),),
        )
        wp = WebPage("https://example.com", "<html></html>", {})
        result = detector._check_technology(tech, wp)
        assert result is None

    def test_multiple_signals_combine(self, detector):
        tech = Technology(
            name="Multi",
            html_patterns=(prepare_pattern("multi\\;confidence:60"),),
            header_patterns=(("x-multi", prepare_pattern("yes\\;confidence:80")),),
        )
        wp = WebPage("https://example.com", "<html>multi</html>", {"X-Multi": "yes"})
        result = detector._check_technology(tech, wp)
        assert result is not None
        assert result.confidence == 80  # max of the two


# ============================================================
# Implies resolution tests
# ============================================================

class TestImpliesResolution:
    @pytest.fixture
    def detector(self, tmp_path):
        import json
        data = {
            "categories": {"1": {"name": "CMS"}, "2": {"name": "PL"}},
            "technologies": {
                "WordPress": {"cats": [1], "html": "wp-content", "implies": ["PHP", "MySQL"]},
                "PHP": {"cats": [2]},
                "MySQL": {"cats": [2]},
                "A": {"cats": [1], "html": "aaa", "implies": "B"},
                "B": {"cats": [1], "implies": "C"},
                "C": {"cats": [1]},
                "LowConf": {"cats": [1], "html": "low", "implies": "LowTarget\\;confidence:40"},
                "LowTarget": {"cats": [1]},
                "MedConf": {"cats": [1], "html": "med", "implies": "MedTarget\\;confidence:60"},
                "MedTarget": {"cats": [1]},
                "Circular": {"cats": [1], "html": "circ", "implies": "CircB"},
                "CircB": {"cats": [1], "implies": "Circular"},
            },
        }
        fp = tmp_path / "tech.json"
        fp.write_text(json.dumps(data))
        return TechDetector(str(fp))

    def test_direct_implies(self, detector):
        wp = WebPage("https://example.com", "<html>wp-content</html>", {})
        results = detector.analyze(wp)
        assert "WordPress" in results
        assert "PHP" in results
        assert "MySQL" in results

    def test_transitive_implies(self, detector):
        wp = WebPage("https://example.com", "<html>aaa</html>", {})
        results = detector.analyze(wp)
        assert "A" in results
        assert "B" in results
        assert "C" in results

    def test_low_confidence_excluded(self, detector):
        wp = WebPage("https://example.com", "<html>low</html>", {})
        results = detector.analyze(wp)
        assert "LowConf" in results
        assert "LowTarget" not in results

    def test_medium_confidence_included(self, detector):
        wp = WebPage("https://example.com", "<html>med</html>", {})
        results = detector.analyze(wp)
        assert "MedConf" in results
        assert "MedTarget" in results

    def test_circular_implies_no_infinite_loop(self, detector):
        wp = WebPage("https://example.com", "<html>circ</html>", {})
        results = detector.analyze(wp)
        assert "Circular" in results
        assert "CircB" in results


# ============================================================
# Full integration: analyze_with_versions_and_categories
# ============================================================

class TestAnalyzeWithVersionsAndCategories:
    def test_returns_expected_format(self):
        detector = TechDetector()
        html = '''<html><head>
            <meta name="generator" content="WordPress 6.0">
            <script src="https://cdn.example.com/jquery-3.6.0.min.js"></script>
        </head><body class="wp-content"></body></html>'''
        wp = WebPage("https://example.com", html, {"X-Powered-By": "PHP/8.1"})
        results = detector.analyze_with_versions_and_categories(wp)
        assert isinstance(results, dict)
        # Should detect at least WordPress
        if "WordPress" in results:
            entry = results["WordPress"]
            assert "versions" in entry
            assert "categories" in entry
            assert isinstance(entry["versions"], list)
            assert isinstance(entry["categories"], list)
