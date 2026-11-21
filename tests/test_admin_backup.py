from tests.conftest import login, make_user
from app.core.models import Setting
from app.core.backup import run_backup, needs_catchup, set_setting
from app.core.database import SessionLocal

def test_dashboard_loads(client, db):
    make_user(db, "mgr", "manager")
    login(client, "mgr")
    r = client.get("/admin/")
    assert r.status_code == 200
    assert "SKU Aktif" in r.text or "Active SKUs" in r.text

def test_settings_update(client, db):
    make_user(db, "own", "owner")
    login(client, "own")
    csrf = client.cookies.get("csrf")
    r = client.post("/admin/settings", data={
        "csrf_token": csrf, "qr_base_url": "http://192.168.1.50:8000",
        "backup_keep_days": "14", "backup_time": "18:00"
    }, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("msg=settings.updated")

    assert db.query(Setting).filter_by(key="qr_base_url").first().value == "http://192.168.1.50:8000"

def test_backup_run_and_list(client, db):
    make_user(db, "own", "owner")
    login(client, "own")
    csrf = client.cookies.get("csrf")

    # Run backup
    r = client.post("/admin/backups/run", data={"csrf_token": csrf}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("msg=backup.success")

    # Check list
    r = client.get("/admin/backups")
    assert r.status_code == 200
    assert "gudang_" in r.text

def test_needs_catchup_logic(client, db):
    set_setting(db, "backup_last_at", "")
    assert needs_catchup(db) is True

    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    old_time = (datetime.now(ZoneInfo("Asia/Jakarta")) - timedelta(hours=25)).strftime("%Y%m%d_%H%M%S")
    set_setting(db, "backup_last_at", old_time)
    assert needs_catchup(db) is True

    new_time = (datetime.now(ZoneInfo("Asia/Jakarta")) - timedelta(hours=5)).strftime("%Y%m%d_%H%M%S")
    set_setting(db, "backup_last_at", new_time)
    assert needs_catchup(db) is False
