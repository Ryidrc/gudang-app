"""Pre-start: generate config.toml, safety-backup DB, print LAN IP."""
from __future__ import annotations

import secrets
import socket
import sqlite3
import sys
from datetime import datetime

from app.core.config import CONFIG_PATH, DATA_DIR, DB_PATH, EXAMPLE_CONFIG_PATH


def ensure_config() -> None:
    if CONFIG_PATH.exists():
        return
    text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
    token = secrets.token_urlsafe(32)
    text = text.replace('secret_key = ""', f'secret_key = "{token}"', 1)
    CONFIG_PATH.write_text(text, encoding="utf-8")
    print("[prestart] config.toml created with a random secret_key.")


def safety_backup() -> None:
    if not DB_PATH.exists():
        return
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"gudang_prestart_{stamp}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    print(f"[prestart] safety backup -> {target.name}")


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no packet actually sent
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main() -> int:
    ensure_config()
    safety_backup()
    ip = lan_ip()
    print(f"[prestart] LAN IP: {ip} -> later set qr_base_url to http://{ip}:8000")
    # qr_base_url drift warning lands in I6 (needs the settings table).
    return 0


if __name__ == "__main__":
    sys.exit(main())
