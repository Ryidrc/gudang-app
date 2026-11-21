"""App factory — wiring only, no business logic."""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import routes as admin_routes
from app.auth import routes as auth_routes
from app.auth import services as auth_services
from app.core.config import BASE_DIR, security_cfg
from app.core.context import set_csrf, set_ip, set_locale, set_user
from app.core import database
from app.core.database import get_db
from app.core.deps import LoginRequired, current_user
from app.core.i18n import DEFAULT_LOCALE, SUPPORTED, t
from app.core.security import CSRF_COOKIE, SID_COOKIE, make_csrf_token
from app.warehouse.models import StockRequest

UNSAFE = ("POST", "PUT", "PATCH", "DELETE")
# Paths a user with a pending forced password change may still reach.
PASSWORD_CHANGE_PATHS = ("/profile", "/logout", "/locale/set")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.core.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()


def _is_form_type(ctype: str) -> bool:
    return ctype.startswith(("application/x-www-form-urlencoded", "multipart/form-data"))


async def _read_form(request: Request) -> dict:
    """Parse the request body once; downstream handlers use request.state.form_cache."""
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/x-www-form-urlencoded"):
        body = await request.body()
        return dict(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))
    if ctype.startswith("multipart/form-data"):
        return dict(await request.form())
    return {}


def create_app() -> FastAPI:
    app = FastAPI(title="Gudang App", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")

    @app.middleware("http")
    async def gudang_context(request: Request, call_next):
        # Static assets need no DB session, locale, or CSRF context.
        if request.url.path.startswith("/static/"):
            return await call_next(request)
        # 1. locale
        loc = request.cookies.get("lang", DEFAULT_LOCALE)
        set_locale(loc if loc in SUPPORTED else DEFAULT_LOCALE)
        # 2. csrf cookie (ensure present)
        csrf = request.cookies.get(CSRF_COOKIE)
        fresh_csrf = None
        if not csrf:
            csrf = make_csrf_token()
            fresh_csrf = csrf
        set_csrf(csrf)
        set_ip(request.client.host if request.client else None)
        # 3. per-request DB session and auth state
        db = database.SessionLocal()
        request.state.db = db
        request.state.form_cache = {}
        request.state.session = None
        request.state.user = None
        request.state.pending_requests = 0
        set_user(None)
        try:
            signed = request.cookies.get(SID_COOKIE)
            if signed:
                resolved = auth_services.resolve_session(
                    db, signed, request.headers.get("user-agent"),
                    request.client.host if request.client else None)
                if resolved is not None:
                    request.state.user, request.state.session = resolved
                    set_user(request.state.user)

            # 4. CSRF on every state-changing request, authenticated or not.
            if request.method in UNSAFE:
                if _is_form_type(request.headers.get("content-type", "")):
                    request.state.form_cache = await _read_form(request)
                provided = request.headers.get("x-csrf-token") or \
                    request.state.form_cache.get("csrf_token")
                if not provided or not secrets.compare_digest(str(provided), csrf):
                    from app.core.templates import get_templates
                    return get_templates().TemplateResponse(
                        request, "error.html", {"msg": t("error.403")}, status_code=403)

            # 5. Forced password change after an admin reset.
            user = request.state.user
            if user is not None and user.must_change_password:
                path = request.url.path
                if not any(path == p or path.startswith(p + "/")
                           for p in PASSWORD_CHANGE_PATHS):
                    return RedirectResponse("/profile?msg=profile.must_change", status_code=302)

            # 6. Pending-approval badge for reviewers.
            if user is not None and user.role in ("owner", "manager"):
                request.state.pending_requests = db.scalar(
                    select(func.count(StockRequest.id)).where(StockRequest.status == "pending")) or 0

            response = await call_next(request)
        finally:
            db.close()
        if fresh_csrf:
            response.set_cookie(CSRF_COOKIE, fresh_csrf, max_age=315360000,
                                httponly=False, samesite="lax",
                                secure=security_cfg()["cookie_secure"], path="/")
        return response

    @app.exception_handler(LoginRequired)
    async def login_required_handler(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/login?next={quote(exc.next_url)}", status_code=302)

    @app.exception_handler(HTTPException)
    async def http_exc_handler(request: Request, exc: HTTPException):
        if exc.status_code in (403, 404):
            from app.core.templates import get_templates
            templates = get_templates()
            key = "error.403" if exc.status_code == 403 else "error.404"
            return templates.TemplateResponse(request, "error.html",
                                              {"msg": t(key)}, status_code=exc.status_code)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    from app.core.templates import get_templates
    templates = get_templates()

    # Imported late so the template registry is initialized first.
    from app.warehouse import routes as warehouse_routes

    app.include_router(auth_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(warehouse_routes.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, db: Session = Depends(get_db)):
        user = current_user(request)
        if user is None:
            raise LoginRequired(next_url="/")
        from app.admin.services import dashboard_stats
        return templates.TemplateResponse(request, "admin/dashboard.html", dashboard_stats(db, user))

    return app



app = create_app()
