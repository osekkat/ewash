"""Tests for app.api_validation.clean_text — free-text input sanitizer."""
from __future__ import annotations

from app.api_validation import clean_text


def test_clean_text_returns_none_for_none():
    assert clean_text(None, max_len=100) is None


def test_clean_text_strips_outer_whitespace():
    assert clean_text("  hello  ", max_len=100) == "hello"


def test_clean_text_strips_control_characters():
    # NUL, BEL, BS, VT, FF, ESC — all category Cc.
    assert clean_text("foo\x00bar", max_len=100) == "foobar"
    assert clean_text("foo\x07bar", max_len=100) == "foobar"
    assert clean_text("foo\x1bbar", max_len=100) == "foobar"


def test_clean_text_collapses_internal_horizontal_whitespace():
    assert clean_text("foo    bar", max_len=100) == "foo bar"


def test_clean_text_strips_tabs_along_with_other_controls():
    # Tab is Unicode category Cc — stripped like NUL/BEL/ESC. The surrounding
    # spaces survive and then collapse normally.
    assert clean_text("foo\t\tbar", max_len=100) == "foobar"
    assert clean_text("foo \t \t bar", max_len=100) == "foo bar"


def test_clean_text_preserves_newlines():
    # Notes must keep their line breaks: "Sonner deux fois\nÉtage 3, porte gauche".
    assert clean_text("foo\nbar", max_len=100) == "foo\nbar"
    assert clean_text("line 1\nline 2\nline 3", max_len=100) == "line 1\nline 2\nline 3"


def test_clean_text_truncates_to_max_len():
    assert clean_text("a" * 500, max_len=100) == "a" * 100


def test_clean_text_returns_none_when_only_whitespace():
    assert clean_text("   ", max_len=100) is None
    assert clean_text("\t\t", max_len=100) is None
    assert clean_text("", max_len=100) is None


def test_clean_text_returns_none_when_only_control_chars():
    # Stripping all category Cc characters leaves nothing.
    assert clean_text("\x00\x01\x02", max_len=100) is None


def test_clean_text_keeps_unicode_letters_and_accents():
    assert clean_text("café — étage 3", max_len=100) == "café — étage 3"
    assert clean_text("شارع الحرية", max_len=100) == "شارع الحرية"


def test_clean_text_truncation_after_strip_not_before():
    # 5 leading spaces + "hello" → strip → "hello" → cap at 100 → "hello".
    # If truncation ran first, max_len=3 would yield "   " then strip to None.
    assert clean_text("     hello", max_len=3) == "hel"


def test_clean_text_combines_passes_idempotently():
    # Control + whitespace + length: combined cleaning still produces the
    # expected normalized output.
    raw = "  foo\x00   bar\nbaz\t\t  qux  "
    assert clean_text(raw, max_len=100) == "foo bar\nbaz qux"
