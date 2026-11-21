"""Backup and restore logic."""
from __future__ import annotations

import os
import sqlite3
import glob
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.config import DB_PATH, DATA_DIR
from app.core.models import write_audit, utcnow

BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

def get_setting(db, key: str, default: str) -> str:
    from app.core.models import Setting
    row = db.query(Setting).filter_by(key=key).first()
    return row.value if row else default

def set_setting(db, key: str, value: str):
    from app.core.models import Setting
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.flush()  # read-your-writes: routes/schedulers often re-read before commit

def run_backup(db, actor=None) -> dict:
    """Perform SQLite online backup, prune old files, update settings."""
    timestamp = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y%m%d_%H%M%S")
    filename = f"gudang_{timestamp}.db"
    target_path = BACKUP_DIR / filename

    try:
        # Online backup API (safe for WAL mode)
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(str(target_path))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()

        # Prune old backups
        keep_days = int(get_setting(db, "backup_keep_days", "7"))
        cutoff = datetime.now() - timedelta(days=keep_days)
        deleted_count = 0
        for f in BACKUP_DIR.glob("gudang_*.db"):
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                deleted_count += 1

        # Update settings
        set_setting(db, "backup_last_at", timestamp)
        db.commit()

        write_audit(db, actor, "backup.run", "backup", None,
                    after={"filename": filename, "pruned": deleted_count})
        db.commit()
        return {"success": True, "filename": filename, "pruned": deleted_count}
    except Exception as e:
        write_audit(db, actor, "backup.fail", "backup", None, after={"error": str(e)})
        db.commit()
        return {"success": False, "error": str(e)}

def needs_catchup(db) -> bool:
    last_at = get_setting(db, "backup_last_at", "")
    if not last_at:
        return True
    try:
        # last_at is stored as YYYYMMDD_HHMMSS
        dt = datetime.strptime(last_at, "%Y%m%d_%H%M%S").replace(tzinfo=ZoneInfo("Asia/Jakarta"))
        return (datetime.now(ZoneInfo("Asia/Jakarta")) - dt) > timedelta(hours=20)
    except ValueError:
        return True
