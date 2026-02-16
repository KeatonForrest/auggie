"""Tests for cursor-based pagination helpers."""

import base64

import pytest

from api.pagination import (
    encode_cursor,
    decode_cursor,
    encode_composite_cursor,
    decode_composite_cursor,
)


class TestCursorEncoding:
    def test_round_trip(self):
        """encode then decode returns the original value."""
        original = "42"
        encoded = encode_cursor(original)
        assert decode_cursor(encoded) == original

    def test_round_trip_string(self):
        original = "some_value:with:colons"
        assert decode_cursor(encode_cursor(original)) == original

    def test_encoded_is_url_safe(self):
        """Encoded cursor should not contain +, /, or = (urlsafe base64)."""
        for val in ["100", "999999", "special/chars+here"]:
            encoded = encode_cursor(val)
            assert "+" not in encoded
            assert "/" not in encoded


class TestCompositeCursor:
    def test_round_trip_numeric(self):
        """Composite cursor with a numeric sort value."""
        encoded = encode_composite_cursor(85, 42)
        sort_val, item_id = decode_composite_cursor(encoded)
        assert sort_val == "85"
        assert item_id == 42

    def test_round_trip_null(self):
        """Composite cursor with None sort value."""
        encoded = encode_composite_cursor(None, 7)
        sort_val, item_id = decode_composite_cursor(encoded)
        assert sort_val is None
        assert item_id == 7

    def test_round_trip_string_value(self):
        """Composite cursor with a string sort value."""
        encoded = encode_composite_cursor("Acme Corp", 3)
        sort_val, item_id = decode_composite_cursor(encoded)
        assert sort_val == "Acme Corp"
        assert item_id == 3

    def test_different_values_produce_different_cursors(self):
        c1 = encode_composite_cursor(80, 1)
        c2 = encode_composite_cursor(90, 1)
        c3 = encode_composite_cursor(80, 2)
        assert c1 != c2
        assert c1 != c3


class TestInvalidCursor:
    def test_malformed_base64(self):
        """Non-base64 string should raise an exception."""
        with pytest.raises(Exception):
            decode_composite_cursor("not!valid!base64@@@")

    def test_missing_colon(self):
        """Base64 of a string without a colon should raise (no split possible)."""
        no_colon = base64.urlsafe_b64encode(b"nocolon").decode()
        with pytest.raises(Exception):
            decode_composite_cursor(no_colon)

    def test_non_integer_id(self):
        """Base64 of 'value:notanumber' should raise ValueError from int()."""
        bad_id = base64.urlsafe_b64encode(b"85:notanumber").decode()
        with pytest.raises(Exception):
            decode_composite_cursor(bad_id)
