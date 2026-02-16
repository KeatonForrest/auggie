"""Unit tests for utils.slugs.slugify()."""

from utils.slugs import slugify


def test_basic_slugification():
    assert slugify("Acme Corp") == "acme-corp"


def test_special_characters():
    assert slugify("Ben & Jerry's Ice Cream") == "ben-jerry-s-ice-cream"


def test_unicode_normalization():
    assert slugify("Cafe\u0301 Mu\u0308nchen") == "cafe-munchen"


def test_empty_string():
    assert slugify("") == "untitled"


def test_all_special_characters():
    assert slugify("!!!@@@###") == "untitled"


def test_long_name_truncated():
    long_name = "a" * 100
    result = slugify(long_name, max_length=80)
    assert len(result) <= 80


def test_long_name_truncates_at_word_boundary():
    # "alpha-beta-gamma" repeated — should truncate cleanly at a hyphen
    name = "alpha beta gamma delta " * 10
    result = slugify(name, max_length=30)
    assert len(result) <= 30
    assert not result.endswith("-")


def test_hyphen_collapsing():
    assert slugify("foo---bar") == "foo-bar"


def test_leading_trailing_hyphens_stripped():
    assert slugify("  --hello world--  ") == "hello-world"


def test_numbers_preserved():
    assert slugify("Company 42") == "company-42"


def test_already_slug_like():
    assert slugify("my-company") == "my-company"


def test_single_word():
    assert slugify("Salesforce") == "salesforce"


def test_max_length_exact():
    result = slugify("ab", max_length=2)
    assert result == "ab"


def test_whitespace_only():
    assert slugify("   ") == "untitled"


def test_strips_com_tld():
    assert slugify("F5.com") == "f5"


def test_strips_io_tld():
    assert slugify("Linear.io") == "linear"


def test_strips_ai_tld():
    assert slugify("Anthropic.ai") == "anthropic"


def test_preserves_tld_in_middle():
    assert slugify("Comm.unity Platform") == "comm-unity-platform"


def test_strips_tld_case_insensitive():
    assert slugify("Vercel.COM") == "vercel"
