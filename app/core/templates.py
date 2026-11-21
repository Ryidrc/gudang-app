"""Centralized Jinja2 templates configuration."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.core.config import BASE_DIR
from app.core.i18n import jinja_globals

_templates = None
JAKARTA = ZoneInfo("Asia/Jakarta")


def _as_jakarta(value: datetime) -> datetime:
    """DB stores naive UTC; render in Asia/Jakarta."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(JAKARTA)


def datetimeformat(value, format="%d/%m/%Y %H:%M"):
    """Format a UTC datetime or Unix timestamp for display in Asia/Jakarta."""
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, tz=JAKARTA)
    return _as_jakarta(value).strftime(format)


def get_templates() -> Jinja2Templates:
    global _templates
    if _templates is None:
        from app.auth import services as auth_services

        _templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
        _templates.env.globals.update(jinja_globals())
        _templates.env.filters["has_perm"] = (
            lambda u, p: u is not None and p in auth_services.permissions_for(u)
        )
        _templates.env.filters["datetimeformat"] = datetimeformat
    return _templates
