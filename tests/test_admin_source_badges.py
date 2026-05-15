"""Tests for app.admin._source_badge — booking source HTML badge helper."""
from __future__ import annotations

import re

from app.admin import _SOURCE_BADGES, _source_badge


def _strip_tags(html_snippet: str) -> str:
    return re.sub(r"<[^>]+>", "", html_snippet)


def test_source_badge_whatsapp_french():
    snippet = _source_badge("whatsapp", locale="fr")
    assert 'class="badge src-wa"' in snippet
    assert 'title="whatsapp"' in snippet
    assert "📱" in snippet
    assert "WhatsApp" in _strip_tags(snippet)


def test_source_badge_api_french():
    snippet = _source_badge("api", locale="fr")
    assert 'class="badge src-pwa"' in snippet
    assert 'title="api"' in snippet
    assert "🌐" in snippet
    assert "PWA" in _strip_tags(snippet)


def test_source_badge_admin_french():
    snippet = _source_badge("admin", locale="fr")
    assert 'class="badge src-admin"' in snippet
    assert 'title="admin"' in snippet
    assert "👤" in snippet
    assert "Admin" in _strip_tags(snippet)


def test_source_badge_english_locale_renders_same_labels():
    # The three sources happen to share French + English labels today; the
    # test still pins the contract so a future French rename doesn't silently
    # leak into the English admin.
    snippet = _source_badge("api", locale="en")
    assert "PWA" in _strip_tags(snippet)


def test_source_badge_none_defaults_to_whatsapp():
    # Legacy rows persisted before the `source` column existed are stored as
    # NULL/empty. They render as WhatsApp (the only channel that existed).
    snippet = _source_badge(None)
    assert "src-wa" in snippet
    assert "📱" in snippet


def test_source_badge_empty_string_defaults_to_whatsapp():
    snippet = _source_badge("")
    assert "src-wa" in snippet


def test_source_badge_unknown_source_falls_back_to_whatsapp_label():
    # The CSS class falls back too, so an unexpected `source` value can't
    # render with no styling and break the table layout.
    snippet = _source_badge("zapier")
    assert "src-wa" in snippet
    assert "WhatsApp" in _strip_tags(snippet)


def test_source_badge_escapes_unknown_source_in_attribute():
    # XSS defense: the raw `source` value flows into the title= attribute and
    # must be HTML-escaped. The label text path falls back to the WhatsApp
    # display, so injection through the visible label is mechanically
    # impossible — but the attribute is the realistic vector.
    snippet = _source_badge('"><script>alert(1)</script>')
    assert "<script>" not in snippet
    assert "&lt;script&gt;" in snippet or "&quot;" in snippet


def test_source_badge_registry_contains_three_sources():
    # Pin the public registry — additions force a conscious choice about
    # CSS class + emoji per new source.
    assert set(_SOURCE_BADGES.keys()) == {"whatsapp", "api", "admin"}
