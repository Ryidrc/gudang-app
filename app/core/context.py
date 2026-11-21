"""Per-request contextvars: locale, csrf token, current user, client IP."""
from __future__ import annotations

from contextvars import ContextVar

from app.core.i18n import DEFAULT_LOCALE

_locale: ContextVar[str] = ContextVar("locale", default=DEFAULT_LOCALE)
_csrf: ContextVar[str] = ContextVar("csrf", default="")
_user: ContextVar[object | None] = ContextVar("user", default=None)
_ip: ContextVar[str | None] = ContextVar("ip", default=None)


def set_locale(v: str) -> None: _locale.set(v)
def current_locale() -> str: return _locale.get()
def set_csrf(v: str) -> None: _csrf.set(v)
def current_csrf() -> str: return _csrf.get()
def set_user(v) -> None: _user.set(v)
def current_user() -> object | None: return _user.get()
def set_ip(v: str | None) -> None: _ip.set(v)
def current_ip() -> str | None: return _ip.get()
