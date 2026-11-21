"""i18n loader. app/i18n/id.json is the source of truth; en.json mirrors keys."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

I18N_DIR = Path(__file__).resolve().parents[1] / "i18n"
SUPPORTED = ("id", "en")
DEFAULT_LOCALE = "id"


@lru_cache
def _load(locale: str) -> dict[str, str]:
    with (I18N_DIR / f"{locale}.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def t(key: str, locale: str | None = None, **fmt) -> str:
    from app.core.context import current_locale
    loc = locale or current_locale()
    loc = loc if loc in SUPPORTED else DEFAULT_LOCALE
    text = _load(loc).get(key) or _load(DEFAULT_LOCALE).get(key) or key
    return text.format(**fmt) if fmt else text


def jinja_globals() -> dict:
    from app.core.context import current_csrf, current_user
    return {
        "_": lambda key, **fmt: t(key, **fmt),
        "csrf_token": current_csrf,
        "user": current_user,
    }
