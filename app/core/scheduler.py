"""APScheduler setup for automated backups."""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.database import SessionLocal
from app.core.backup import run_backup, needs_catchup, set_setting

import os

scheduler = BackgroundScheduler(timezone=ZoneInfo("Asia/Jakarta"))
_started = False

def _scheduled_backup():
    """Executes the backup job."""
    db = SessionLocal()
    try:
        run_backup(db, actor=None)
    finally:
        db.close()

def _backup_trigger(db) -> CronTrigger:
    from app.core.backup import get_setting
    raw = get_setting(db, "backup_time", "17:10")
    try:
        hour, minute = (int(x) for x in raw.split(":", 1))
    except (TypeError, ValueError):
        hour, minute = 17, 10
    return CronTrigger(hour=hour, minute=minute, timezone=ZoneInfo("Asia/Jakarta"))


def reschedule_backup(db) -> None:
    """Apply the DB-stored backup time to a running scheduler."""
    if os.environ.get("GUDANG_TEST") == "1" or not scheduler.running:
        return
    scheduler.add_job(_scheduled_backup, _backup_trigger(db), id="daily_backup",
                      replace_existing=True)


def start_scheduler():
    global _started
    # HARD STOP: Do not run scheduler during tests
    if os.environ.get("GUDANG_TEST") == "1" or _started:
        return

    db = SessionLocal()
    try:
        scheduler.add_job(_scheduled_backup, _backup_trigger(db),
                          id="daily_backup", replace_existing=True)
        # Catch-up logic on startup
        if needs_catchup(db):
            _scheduled_backup()
            set_setting(db, "backup_last_at",
                        datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y%m%d_%H%M%S"))
            db.commit()
    finally:
        db.close()

    scheduler.start()
    _started = True

def stop_scheduler():
    global _started
    if scheduler.running:
        scheduler.shutdown()
        _started = False
