"""French-first admin portal routes.

This is the v0.3 shell. It is intentionally inert until admin credentials are
configured, so deploying the implementation slice does not expose booking ops.
"""
from __future__ import annotations

import hmac
import secrets
import time
from hashlib import sha256
from html import escape
from urllib.parse import parse_qs

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from .admin_i18n import SUPPORTED_LOCALES, admin_nav_labels, normalize_locale, t
from .config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
_SESSION_COOKIE = "ewash_admin_session"


def _session_signature(timestamp: str) -> str:
    return hmac.new(
        settings.admin_password.encode("utf-8"),
        timestamp.encode("utf-8"),
        sha256,
    ).hexdigest()


def _make_session_token() -> str:
    timestamp = str(int(time.time()))
    return f"{timestamp}:{_session_signature(timestamp)}"


def _valid_session_token(token: str | None) -> bool:
    if not settings.admin_password or not token or ":" not in token:
        return False
    timestamp, signature = token.split(":", 1)
    if not timestamp.isdigit():
        return False
    max_age = settings.admin_session_ttl_seconds
    if max_age > 0 and int(time.time()) - int(timestamp) > max_age:
        return False
    return secrets.compare_digest(signature, _session_signature(timestamp))


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


def _password_form(*, locale: str, error: str = "") -> HTMLResponse:
    title = t("admin.password.title", locale)
    error_html = f'<p role="alert"><strong>{escape(error)}</strong></p>' if error else ""
    body = f"""
<h1>{escape(title)}</h1>
{error_html}
<form method="post" action="/admin?lang={escape(locale)}">
  <label for="password">{escape(t('admin.password.label', locale))}</label><br>
  <input id="password" name="password" type="password" autocomplete="current-password" autofocus required>
  <button type="submit">{escape(t('admin.password.submit', locale))}</button>
</form>"""
    return HTMLResponse(content=_layout(locale=locale, title=title, body=body), status_code=200)


def _dashboard(*, locale: str) -> HTMLResponse:
    title = t("nav.dashboard", locale)
    body = (
        f"<h1>{escape(title)}</h1>"
        f"<p><strong>{escape(t('admin.dashboard.version_label', locale))}</strong> "
        "v0.3.0-alpha4</p>"
        f"<p>{escape(t('admin.dashboard.placeholder', locale))}</p>"
        f'<p><a href="/admin/logout">{escape(t("nav.logout", locale))}</a></p>'
    )
    return HTMLResponse(content=_layout(locale=locale, title=title, body=body), status_code=200)


@router.get("", response_class=HTMLResponse)
async def admin_index(request: Request, lang: str | None = Query(default=None)) -> HTMLResponse:
    locale = normalize_locale(lang or settings.admin_default_locale)

    if not settings.admin_password:
        title = t("admin.not_configured.title", locale)
        body = (
            f"<h1>{escape(title)}</h1>"
            f"<p>{escape(t('admin.not_configured.body', locale))}</p>"
        )
        return HTMLResponse(
            content=_layout(locale=locale, title=title, body=body),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if not _valid_session_token(request.cookies.get(_SESSION_COOKIE)):
        return _password_form(locale=locale)

    return _dashboard(locale=locale)


@router.post("", response_class=HTMLResponse)
async def admin_password_submit(request: Request, lang: str | None = Query(default=None)) -> HTMLResponse:
    locale = normalize_locale(lang or settings.admin_default_locale)
    if not settings.admin_password:
        return RedirectResponse(url=f"/admin?lang={locale}", status_code=status.HTTP_303_SEE_OTHER)

    raw_body = (await request.body()).decode("utf-8")
    supplied_password = parse_qs(raw_body).get("password", [""])[0]
    if not secrets.compare_digest(supplied_password, settings.admin_password):
        return HTMLResponse(
            content=_password_form(locale=locale, error=t("admin.password.invalid", locale)).body.decode("utf-8"),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=_SESSION_COOKIE,
        value=_make_session_token(),
        max_age=settings.admin_session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def admin_logout() -> RedirectResponse:
    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(_SESSION_COOKIE)
    return response
