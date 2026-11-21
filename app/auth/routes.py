"""Auth routes: login, logout, profile, locale."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session as DbSession

from app.auth import services
from app.auth.models import User
from app.core.config import security_cfg
from app.core.database import get_db
from app.core.deps import current_user, require_perm
from app.core.i18n import SUPPORTED, t
from app.core.models import write_audit
from app.core.security import (CSRF_COOKIE, LANG_COOKIE, SID_COOKIE, TEN_YEARS,
                               sign_session_token)
from app.core.templates import get_templates

router = APIRouter()
templates = get_templates()


def _safe_next(next_url: str | None) -> str:
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str | None = None):
    if current_user(request) is not None:
        return RedirectResponse(_safe_next(next), status_code=302)
    return templates.TemplateResponse(request, "auth/login.html",
                                      {"next": _safe_next(next)})


@router.post("/login")
def login_submit(request: Request, db: DbSession = Depends(get_db)):
    form = request.state.form_cache
    username = form.get("username", "")
    password = form.get("password", "")
    next_url = _safe_next(form.get("next"))
    user = services.authenticate(db, username, password)
    if user is None:
        services.record_failed_login(db, username, request.client.host if request.client else None)
        return templates.TemplateResponse(request, "auth/login.html",
                                          {"next": next_url, "error": t("login.error.bad")},
                                          status_code=401)
    row = services.create_session(db, user, request.headers.get("user-agent"),
                                  request.client.host if request.client else None)
    write_audit(db, user, "auth.login", "user", user.id)
    db.commit()
    resp = RedirectResponse(next_url, status_code=302)
    resp.set_cookie(SID_COOKIE, sign_session_token(row.token_plain),
                    max_age=TEN_YEARS, httponly=True, samesite="lax",
                    secure=security_cfg()["cookie_secure"], path="/")
    return resp


@router.post("/logout")
def logout(request: Request, db: DbSession = Depends(get_db)):
    user = current_user(request)
    row = getattr(request.state, "session", None)
    if row is not None:
        services.revoke_session(db, row)
        write_audit(db, user, "auth.logout", "user", user.id if user else None)
        db.commit()
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(SID_COOKIE, path="/")
    return resp


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, user: User = Depends(require_perm()),
                 msg: str | None = None):
    return templates.TemplateResponse(
        request, "profile.html",
        {"msg": t(msg) if msg else None, "msg_bad": msg == "profile.pw_wrong"})


@router.post("/profile/password")
def profile_password(request: Request, user: User = Depends(require_perm()),
                     db: DbSession = Depends(get_db)):
    form = request.state.form_cache
    current = form.get("current_password", "")
    new = form.get("new_password", "")
    confirm = form.get("confirm_password", "")
    msg_key, status = None, 200
    if new != confirm:
        msg_key, status = "profile.pw_mismatch", 400
    elif len(new) < 8:
        msg_key, status = "profile.pw_short", 400
    elif not services.change_own_password(db, user, current, new):
        msg_key, status = "profile.pw_wrong", 400
    else:
        row = getattr(request.state, "session", None)
        services.revoke_all_sessions(db, user.id)
        if row is not None:  # keep current session alive
            row.revoked_at = None
            db.commit()
        msg_key = "profile.changed"
    return templates.TemplateResponse(request, "profile.html",
                                      {"msg": t(msg_key) if msg_key else None,
                                       "msg_bad": status != 200},
                                      status_code=status)


@router.get("/locale/set")
def locale_set(request: Request, loc: str = "id", next: str | None = None):
    loc = loc if loc in SUPPORTED else "id"
    resp = RedirectResponse(_safe_next(next), status_code=302)
    resp.set_cookie(LANG_COOKIE, loc, max_age=TEN_YEARS, samesite="lax",
                    secure=security_cfg()["cookie_secure"], path="/")
    return resp
