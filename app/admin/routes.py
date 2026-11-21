"""Admin routes: dashboard, users, settings, backups, audit."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session as DbSession

from app.auth import services as auth_services
from app.auth.models import FailedLogin, User
from app.core.database import get_db
from app.core.deps import require_perm
from app.core.models import AuditLog, Setting, write_audit
from app.core.pagination import paginate
from app.core.templates import get_templates
from app.warehouse.models import Sku, Stock, StockRequest
from app.core.backup import BACKUP_DIR, run_backup, set_setting

from app.admin.services import dashboard_stats

router = APIRouter(prefix="/admin")
templates = get_templates()



def _redirect_admin(path: str, msg_key: str) -> RedirectResponse:
    return RedirectResponse(f"/admin/{path}?msg={msg_key}", status_code=302)


def _get_target(db: DbSession, user_id: int) -> User | None:
    return db.get(User, user_id)


# ================= DASHBOARD =================
@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, actor: User = Depends(require_perm("warehouse.view")),
              db: DbSession = Depends(get_db)):
    from app.admin.services import dashboard_stats
    return templates.TemplateResponse(request, "admin/dashboard.html", dashboard_stats(db, actor))


# ================= USERS =================
@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, actor: User = Depends(require_perm("admin.users")),
               db: DbSession = Depends(get_db), msg: str | None = None, page: int = 1):
    stmt = select(User).order_by(User.username)
    if request.query_params.get("export") == "xlsx":
        from app.core.xlsx import export_xlsx
        rows = [{"Username": u.username, "Tampilan": u.display_name, "Peran": u.role,
                 "Aktif": "Ya" if u.is_active else "Tidak"} for u in db.scalars(stmt).all()]
        return export_xlsx(rows, ["Username", "Tampilan", "Peran", "Aktif"], "users.xlsx")
    users, pg = paginate(db, stmt, page)
    return templates.TemplateResponse(request, "admin/users.html",
                                      {"users": users, "msg": msg, "pg": pg,
                                       "creatable": sorted(auth_services.creatable_roles(actor))})


@router.post("/users")
def users_create(request: Request, actor: User = Depends(require_perm("admin.users")),
                 db: DbSession = Depends(get_db)):
    form = request.state.form_cache
    try:
        auth_services.create_user(db, actor, form.get("username", ""),
                             form.get("display_name", ""), form.get("password", ""),
                             form.get("role", "staff"), form.get("can_record") == "on")
    except ValueError as e:
        key = "users.pw_short" if str(e) == "weak_password" else "users.username_taken"
        return _redirect_admin("users", key)
    return _redirect_admin("users", "users.created")


@router.post("/users/{user_id}/update")
def users_update(user_id: int, request: Request,
                 actor: User = Depends(require_perm("admin.users")),
                 db: DbSession = Depends(get_db)):
    target = _get_target(db, user_id)
    form = request.state.form_cache
    if target is None:
        return _redirect_admin("users", "error.404")
    try:
        auth_services.update_user(db, actor, target,
                             display_name=form.get("display_name"),
                             role=form.get("role"),
                             can_record=form.get("can_record") == "on",
                             is_active=form.get("is_active") == "on")
    except ValueError:
        return _redirect_admin("users", "users.denied")
    return _redirect_admin("users", "users.updated")


@router.post("/users/{user_id}/reset-password")
def users_reset(user_id: int, request: Request,
                actor: User = Depends(require_perm("admin.users")),
                db: DbSession = Depends(get_db)):
    target = _get_target(db, user_id)
    form = request.state.form_cache
    if target is None:
        return _redirect_admin("users", "error.404")
    try:
        auth_services.admin_set_password(db, actor, target, form.get("new_password", ""))
    except ValueError as e:
        key = "users.pw_short" if str(e) == "weak_password" else "users.denied"
        return _redirect_admin("users", key)
    return _redirect_admin("users", "users.pw_reset")


@router.post("/users/{user_id}/revoke-sessions")
def users_revoke(user_id: int, request: Request,
                 actor: User = Depends(require_perm("admin.users")),
                 db: DbSession = Depends(get_db)):
    target = _get_target(db, user_id)
    if target is None:
        return _redirect_admin("users", "error.404")
    if not auth_services.can_manage_user(actor, target):
        return _redirect_admin("users", "users.denied")
    count = auth_services.revoke_all_sessions(db, target.id)
    write_audit(db, actor, "user.sessions_revoked", "user", target.id,
                after={"revoked": count})
    db.commit()
    return _redirect_admin("users", "users.sessions_revoked")


# ================= SETTINGS =================
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, actor: User = Depends(require_perm("admin.settings")),
                  db: DbSession = Depends(get_db), msg: str | None = None):
    settings = {row.key: row.value for row in db.scalars(select(Setting)).all()}
    return templates.TemplateResponse(request, "admin/settings.html",
                                      {"settings": settings, "msg": msg})


@router.post("/settings")
def settings_update(request: Request, actor: User = Depends(require_perm("admin.settings")),
                    db: DbSession = Depends(get_db)):
    f = request.state.form_cache
    set_setting(db, "qr_base_url", f.get("qr_base_url", "http://localhost:8000").rstrip("/"))
    set_setting(db, "backup_keep_days", f.get("backup_keep_days", "7"))
    set_setting(db, "backup_time", f.get("backup_time", "17:10"))
    write_audit(db, actor, "settings.update", "settings", None, after={
        "qr_base_url": f.get("qr_base_url"), "backup_keep_days": f.get("backup_keep_days"),
        "backup_time": f.get("backup_time")})
    db.commit()
    from app.core.scheduler import reschedule_backup
    reschedule_backup(db)
    return _redirect_admin("settings", "settings.updated")


# ================= BACKUPS =================
@router.get("/backups", response_class=HTMLResponse)
def backups_page(request: Request, actor: User = Depends(require_perm("admin.backup")),
                 db: DbSession = Depends(get_db), msg: str | None = None):
    files = []
    for f in sorted(BACKUP_DIR.glob("gudang_*.db"), reverse=True):
        files.append({
            "name": f.name,
            "size": f.stat().st_size,
            "mtime": f.stat().st_mtime
        })
    return templates.TemplateResponse(request, "admin/backups.html",
                                      {"files": files, "msg": msg})


@router.post("/backups/run")
def backup_run(request: Request, actor: User = Depends(require_perm("admin.backup")),
               db: DbSession = Depends(get_db)):
    res = run_backup(db, actor)
    if res["success"]:
        return _redirect_admin("backups", "backup.success")
    return _redirect_admin("backups", "backup.failed")


# ================= AUDIT =================
@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, actor: User = Depends(require_perm("admin.audit")),
               db: DbSession = Depends(get_db), page: int = 1):
    stmt = select(AuditLog).order_by(desc(AuditLog.created_at))
    users = {u.id: u.username for u in db.scalars(select(User)).all()}
    if request.query_params.get("export") == "xlsx":
        from app.core.templates import datetimeformat
        from app.core.xlsx import export_xlsx
        rows = [{"Waktu": datetimeformat(log.created_at, "%d/%m/%Y %H:%M:%S"),
                 "Pengguna": users.get(log.user_id, "System"), "Aksi": log.action,
                 "Entitas": f"{log.entity_type} #{log.entity_id or '-'}",
                 "IP": log.ip or "", "Sebelum": log.before_json or "",
                 "Sesudah": log.after_json or ""} for log in db.scalars(stmt).all()]
        return export_xlsx(rows, ["Waktu", "Pengguna", "Aksi", "Entitas", "IP",
                                  "Sebelum", "Sesudah"], "audit.xlsx")
    logs, pg = paginate(db, stmt, page)
    return templates.TemplateResponse(request, "admin/audit.html",
                                      {"logs": logs, "users": users, "pg": pg})
