"""French-first admin portal routes.

This is the v0.3 shell. It is intentionally inert until admin credentials are
configured, so deploying the implementation slice does not expose booking ops.
"""
from __future__ import annotations

from html import escape

from fastapi import APIRouter, Query, status
from fastapi.responses import HTMLResponse

from .admin_i18n import SUPPORTED_LOCALES, admin_nav_labels, normalize_locale, t
from .config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


def _language_switch(locale: str) -> str:
    links = []
    for supported in SUPPORTED_LOCALES:
        label = supported.upper()
        if supported == locale:
            links.append(f"<strong>{label}</strong>")
        else:
            links.append(f'<a href="?lang={supported}">{label}</a>')
    return " | ".join(links)


def _layout(*, locale: str, title: str, body: str) -> str:
    nav = "".join(f"<li>{escape(label)}</li>" for label in admin_nav_labels(locale))
    return f"""<!doctype html>
<html lang="{escape(locale)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} · Ewash Admin</title>
</head>
<body>
  <header>
    <strong>Ewash Admin</strong>
    <nav aria-label="Admin navigation"><ul>{nav}</ul></nav>
    <p>{_language_switch(locale)}</p>
  </header>
  <main>{body}</main>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
async def admin_index(lang: str | None = Query(default=None)) -> HTMLResponse:
    locale = normalize_locale(lang or settings.admin_default_locale)

    if not settings.admin_password or not settings.admin_session_secret:
        title = t("admin.not_configured.title", locale)
        body = (
            f"<h1>{escape(title)}</h1>"
            f"<p>{escape(t('admin.not_configured.body', locale))}</p>"
        )
        return HTMLResponse(
            content=_layout(locale=locale, title=title, body=body),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    # Real login/dashboard lands here in the next implementation slice.
    title = t("nav.dashboard", locale)
    return HTMLResponse(
        content=_layout(locale=locale, title=title, body=f"<h1>{escape(title)}</h1>"),
        status_code=status.HTTP_200_OK,
    )
