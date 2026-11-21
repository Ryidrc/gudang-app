"""Bootstrap config (config.toml). Runtime settings live in the DB."""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("GUDANG_DB_PATH", DATA_DIR / "app.db"))
CONFIG_PATH = Path(os.environ.get("GUDANG_CONFIG_PATH", BASE_DIR / "config.toml"))
EXAMPLE_CONFIG_PATH = BASE_DIR / "config.example.toml"


@lru_cache
def get_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise RuntimeError("config.toml missing — run: python -m app.core.prestart")
    with CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def server_cfg() -> dict[str, Any]:
    return get_config()["server"]


def security_cfg() -> dict[str, Any]:
    return get_config()["security"]


def secret_key() -> str:
    return get_config()["secrets"]["secret_key"]
