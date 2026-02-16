"""Cursor-based pagination helpers."""

import base64
import json


def encode_cursor(value: str) -> str:
    """Encode a cursor value to a URL-safe base64 string."""
    return base64.urlsafe_b64encode(value.encode()).decode()


def decode_cursor(cursor: str) -> str:
    """Decode a URL-safe base64 cursor back to its original value."""
    return base64.urlsafe_b64decode(cursor.encode()).decode()


def encode_composite_cursor(sort_value, item_id: int) -> str:
    """Encode a composite cursor for sorted pagination.

    The cursor contains both the sort column value and the row ID,
    allowing keyset pagination on arbitrary sort columns.
    """
    sv = "null" if sort_value is None else str(sort_value)
    return encode_cursor(f"{sv}:{item_id}")


def decode_composite_cursor(cursor: str) -> tuple:
    """Decode a composite cursor into (sort_value, item_id).

    Returns (sort_value_str_or_None, item_id_int).
    """
    raw = decode_cursor(cursor)
    parts = raw.rsplit(":", 1)
    sort_val = None if parts[0] == "null" else parts[0]
    item_id = int(parts[1])
    return sort_val, item_id
