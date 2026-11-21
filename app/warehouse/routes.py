"""Warehouse routes: visual explorer (view) + management CRUD (manage)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.auth.models import User
from app.core.database import get_db
from app.core.deps import require_perm
from app.core.i18n import t
from app.core.models import Setting
from app.core.pagination import paginate
from app.core.templates import get_templates
from app.core.xlsx import export_xlsx
from app.warehouse import services
from app.warehouse.models import Area, Gudang, Rak, Sku, Stock, StockRequest
from app.warehouse.qr import generate_qr_png
from app.warehouse.sku_import import (commit_import, discard_upload,
                                      generate_template, load_upload,
                                      parse_file, stash_upload,
                                      validate_against_db)

router = APIRouter()
templates = get_templates()


def _done(path: str, key: str) -> RedirectResponse:
    return RedirectResponse(f"{path}?msg={key}", status_code=302)


def _crumbs(request, *pairs) -> list[tuple[str, str]]:
    crumbs = [("/w", t("w.home"))]
    crumbs.extend(pairs)
    return crumbs


def _qr_base(db: DbSession) -> str:
    row = db.get(Setting, "qr_base_url")
    return (row.value if row else "http://localhost:8000").rstrip("/")


# ================= EXPLORER (warehouse.view) =================

@router.get("/w", response_class=HTMLResponse)
def explorer_home(request: Request, user: User = Depends(require_perm("warehouse.view")),
                  db: DbSession = Depends(get_db)):
    rows = []
    for g in db.scalars(select(Gudang).where(Gudang.is_active.is_(True)).order_by(Gudang.name)):
        n_areas = db.scalar(select(func.count(Area.id)).where(
            Area.gudang_id == g.id, Area.is_active.is_(True))) or 0
        n_raks = db.scalar(select(func.count(Rak.id)).join(Area, Area.id == Rak.area_id).where(
            Area.gudang_id == g.id, Rak.is_active.is_(True))) or 0
        boxes = db.scalar(select(func.coalesce(func.sum(Stock.qty_boxes), 0)).join(
            Rak, Rak.id == Stock.rak_id).join(Area, Area.id == Rak.area_id).where(
            Area.gudang_id == g.id, Stock.qty_boxes > 0)) or 0
        rows.append({"g": g, "areas": n_areas, "raks": n_raks, "boxes": boxes})
    return templates.TemplateResponse(request, "warehouse/home.html", {"rows": rows})


@router.get("/w/gudang/{gid}", response_class=HTMLResponse)
def explorer_gudang(gid: int, request: Request,
                    user: User = Depends(require_perm("warehouse.view")),
                    db: DbSession = Depends(get_db)):
    g = db.get(Gudang, gid)
    if g is None or not g.is_active:
        return _done("/w", "error.404")
    areas = db.scalars(select(Area).where(Area.gudang_id == g.id,
                     Area.is_active.is_(True)).order_by(Area.sort_order, Area.name)).all()
    return templates.TemplateResponse(request, "warehouse/gudang.html",
                                      {"g": g, "areas": areas,
                                       "crumbs": _crumbs(request, (f"/w/gudang/{g.id}", g.name))})


@router.get("/w/area/{aid}", response_class=HTMLResponse)
def explorer_area(aid: int, request: Request,
                  user: User = Depends(require_perm("warehouse.view")),
                  db: DbSession = Depends(get_db)):
    a = db.get(Area, aid)
    if a is None or not a.is_active:
        return _done("/w", "error.404")
    g = db.get(Gudang, a.gudang_id)
    raks = db.scalars(select(Rak).where(Rak.area_id == a.id,
                   Rak.is_active.is_(True)).order_by(Rak.sort_order, Rak.name)).all()
    counts = {}
    for r in raks:
        counts[r.id] = db.scalar(select(func.coalesce(func.sum(Stock.qty_boxes), 0)).where(
            Stock.rak_id == r.id, Stock.qty_boxes > 0)) or 0
    return templates.TemplateResponse(request, "warehouse/area.html",
                                      {"a": a, "g": g, "raks": raks, "counts": counts,
                                       "crumbs": _crumbs(request, (f"/w/gudang/{g.id}", g.name),
                                                          (f"/w/area/{a.id}", a.name))})


@router.get("/w/rak/{rid}", response_class=HTMLResponse)
def explorer_rak(rid: int, request: Request,
                 user: User = Depends(require_perm("warehouse.view")),
                 db: DbSession = Depends(get_db), msg: str | None = None):
    r = db.get(Rak, rid)
    if r is None or not r.is_active:
        return _done("/w", "error.404")
    a = db.get(Area, r.area_id)
    g = db.get(Gudang, a.gudang_id)
    stocks = db.scalars(select(Stock).where(Stock.rak_id == r.id,
                       Stock.qty_boxes > 0).order_by(Stock.id)).all()
    skus = {s.id: s for s in db.scalars(select(Sku)).all()}
    skus_active = db.scalars(select(Sku).where(Sku.is_active.is_(True))
                             .order_by(Sku.code)).all()
    raks_active = []
    for rk in db.scalars(select(Rak).where(Rak.is_active.is_(True))
                         .order_by(Rak.sort_order)).all():
        ar = db.get(Area, rk.area_id)
        gu = db.get(Gudang, ar.gudang_id)
        raks_active.append({"id": rk.id, "label": f"{gu.name} / {ar.name} / {rk.name}"})
    return templates.TemplateResponse(request, "warehouse/rak.html",
                                      {"r": r, "a": a, "g": g, "stocks": stocks, "skus": skus,
                                       "skus_active": skus_active, "raks_active": raks_active,
                                       "msg": msg,
                                       "crumbs": _crumbs(request, (f"/w/gudang/{g.id}", g.name),
                                                          (f"/w/area/{a.id}", a.name),
                                                          (f"/w/rak/{r.id}", r.name))})


# ================= MANAGEMENT (warehouse.manage) =================

@router.get("/manage/gudangs")
def manage_gudangs(request: Request, user: User = Depends(require_perm("warehouse.manage")),
                   db: DbSession = Depends(get_db), msg: str | None = None, page: int = 1):
    stmt = select(Gudang).order_by(Gudang.name)
    if request.query_params.get("export") == "xlsx":
        items = db.scalars(stmt).all()
        rows = [{"Nama": g.name, "Aktif": "Ya" if g.is_active else "Tidak"} for g in items]
        return export_xlsx(rows, ["Nama", "Aktif"], "gudangs.xlsx")
    items, pg = paginate(db, stmt, page)
    return templates.TemplateResponse(request, "warehouse/manage_gudangs.html",
                                      {"items": items, "msg": msg, "pg": pg})


@router.post("/manage/gudangs")
def manage_gudangs_create(request: Request,
                          user: User = Depends(require_perm("warehouse.manage")),
                          db: DbSession = Depends(get_db)):
    try:
        services.create_gudang(db, user, request.state.form_cache.get("name", ""))
        return _done("/manage/gudangs", "manage.created")
    except ValueError:
        return _done("/manage/gudangs", "manage.name_taken")


@router.post("/manage/gudangs/{gid}/update")
def manage_gudangs_update(gid: int, request: Request,
                          user: User = Depends(require_perm("warehouse.manage")),
                          db: DbSession = Depends(get_db)):
    g = db.get(Gudang, gid)
    if g is None:
        return _done("/manage/gudangs", "error.404")
    try:
        services.update_gudang(db, user, g, request.state.form_cache.get("name", ""))
        return _done("/manage/gudangs", "manage.updated")
    except ValueError:
        return _done("/manage/gudangs", "manage.name_taken")


@router.post("/manage/gudangs/{gid}/active")
def manage_gudangs_active(gid: int, request: Request,
                          user: User = Depends(require_perm("warehouse.manage")),
                          db: DbSession = Depends(get_db)):
    g = db.get(Gudang, gid)
    if g is None:
        return _done("/manage/gudangs", "error.404")
    active = request.state.form_cache.get("is_active") == "on"
    try:
        services.set_active(db, user, "gudang", g, active)
        return _done("/manage/gudangs", "manage.reactivated" if active else "manage.archived_ok")
    except ValueError:
        return _done("/manage/gudangs", "manage.has_stock")


@router.get("/manage/areas")
def manage_areas(request: Request, user: User = Depends(require_perm("warehouse.manage")),
                 db: DbSession = Depends(get_db), msg: str | None = None, page: int = 1,
                 gudang_id: int | None = None):
    stmt = select(Area).order_by(Area.gudang_id, Area.sort_order, Area.name)
    gudangs = db.scalars(select(Gudang).where(Gudang.is_active.is_(True))
                         .order_by(Gudang.name)).all()
    gmap = {g.id: g.name for g in db.scalars(select(Gudang)).all()}
    if request.query_params.get("export") == "xlsx":
        items = db.scalars(stmt).all()
        rows = [{"Gudang": gmap[a.gudang_id], "Nama": a.name, "Urutan": a.sort_order,
                 "Aktif": "Ya" if a.is_active else "Tidak"} for a in items]
        return export_xlsx(rows, ["Gudang", "Nama", "Urutan", "Aktif"], "areas.xlsx")
    items, pg = paginate(db, stmt, page)
    return templates.TemplateResponse(request, "warehouse/manage_areas.html",
                                      {"items": items, "gudangs": gudangs, "gmap": gmap,
                                       "msg": msg, "pg": pg, "sel_gudang": gudang_id})


@router.post("/manage/areas")
def manage_areas_create(request: Request, user: User = Depends(require_perm("warehouse.manage")),
                        db: DbSession = Depends(get_db)):
    f = request.state.form_cache
    try:
        services.create_area(db, user, int(f.get("gudang_id", 0)), f.get("name", ""),
                             f.get("sort_order", 0))
        return _done("/manage/areas", "manage.created")
    except (ValueError, TypeError):
        return _done("/manage/areas", "manage.name_taken")


@router.post("/manage/areas/{aid}/update")
def manage_areas_update(aid: int, request: Request,
                        user: User = Depends(require_perm("warehouse.manage")),
                        db: DbSession = Depends(get_db)):
    a = db.get(Area, aid)
    if a is None:
        return _done("/manage/areas", "error.404")
    f = request.state.form_cache
    try:
        services.update_area(db, user, a, f.get("name", ""), f.get("sort_order", a.sort_order))
        return _done("/manage/areas", "manage.updated")
    except ValueError:
        return _done("/manage/areas", "manage.name_taken")


@router.post("/manage/areas/{aid}/active")
def manage_areas_active(aid: int, request: Request,
                        user: User = Depends(require_perm("warehouse.manage")),
                        db: DbSession = Depends(get_db)):
    a = db.get(Area, aid)
    if a is None:
        return _done("/manage/areas", "error.404")
    active = request.state.form_cache.get("is_active") == "on"
    try:
        services.set_active(db, user, "area", a, active)
        return _done("/manage/areas", "manage.reactivated" if active else "manage.archived_ok")
    except ValueError:
        return _done("/manage/areas", "manage.has_stock")


@router.get("/manage/raks", response_class=HTMLResponse)
def manage_raks(request: Request, user: User = Depends(require_perm("warehouse.manage")),
                db: DbSession = Depends(get_db), msg: str | None = None, page: int = 1,
                area_id: int | None = None):
    stmt = select(Rak).order_by(Rak.area_id, Rak.sort_order, Rak.name)
    areas = db.scalars(select(Area).where(Area.is_active.is_(True))
                       .order_by(Area.gudang_id, Area.sort_order)).all()
    amap = {a.id: a.name for a in db.scalars(select(Area)).all()}
    gmap = {g.id: g.name for g in db.scalars(select(Gudang)).all()}
    if request.query_params.get("export") == "xlsx":
        items = db.scalars(stmt).all()
        rows = [{"Area": amap[r.area_id], "Nama": r.name, "Urutan": r.sort_order,
                 "Aktif": "Ya" if r.is_active else "Tidak"} for r in items]
        return export_xlsx(rows, ["Area", "Nama", "Urutan", "Aktif"], "raks.xlsx")
    items, pg = paginate(db, stmt, page)
    return templates.TemplateResponse(request, "warehouse/manage_raks.html",
                                      {"items": items, "areas": areas, "amap": amap,
                                       "gmap": gmap, "msg": msg, "pg": pg,
                                       "sel_area": area_id})


@router.post("/manage/raks")
def manage_raks_create(request: Request,
                       user: User = Depends(require_perm("warehouse.manage")),
                       db: DbSession = Depends(get_db)):
    f = request.state.form_cache
    try:
        services.create_rak(db, user, int(f.get("area_id", 0)), f.get("name", ""),
                            int(f.get("sort_order", 0)))
        return _done("/manage/raks", "manage.created")
    except (ValueError, TypeError):
        return _done("/manage/raks", "manage.name_taken")


@router.post("/manage/raks/{rid}/update")
def manage_raks_update(rid: int, request: Request,
                       user: User = Depends(require_perm("warehouse.manage")),
                       db: DbSession = Depends(get_db)):
    r = db.get(Rak, rid)
    if r is None:
        return _done("/manage/raks", "error.404")
    f = request.state.form_cache
    try:
        services.update_rak(db, user, r, f.get("name", ""), f.get("sort_order", r.sort_order))
        return _done("/manage/raks", "manage.updated")
    except ValueError:
        return _done("/manage/raks", "manage.name_taken")


@router.post("/manage/raks/{rid}/active")
def manage_raks_active(rid: int, request: Request,
                       user: User = Depends(require_perm("warehouse.manage")),
                       db: DbSession = Depends(get_db)):
    r = db.get(Rak, rid)
    if r is None:
        return _done("/manage/raks", "error.404")
    active = request.state.form_cache.get("is_active") == "on"
    try:
        services.set_active(db, user, "rak", r, active)
        return _done("/manage/raks", "manage.reactivated" if active else "manage.archived_ok")
    except ValueError:
        return _done("/manage/raks", "manage.has_stock")


@router.get("/manage/skus")
def manage_skus(request: Request, user: User = Depends(require_perm("warehouse.manage")),
                db: DbSession = Depends(get_db), page: int = 1):
    stmt = select(Sku).order_by(Sku.code)
    if request.query_params.get("export") == "xlsx":
        items = db.scalars(stmt).all()
        rows = [{"Kode": s.code, "Nama": s.name, "Deskripsi": s.description or "",
                 "Aktif": "Ya" if s.is_active else "Tidak"} for s in items]
        return export_xlsx(rows, ["Kode", "Nama", "Deskripsi", "Aktif"], "skus_export.xlsx")
    items, pg = paginate(db, stmt, page)
    return templates.TemplateResponse(request, "warehouse/manage_skus.html",
                                      {"items": items, "pg": pg,
                                       "msg": request.query_params.get("msg")})


@router.post("/manage/skus")
def manage_skus_create(request: Request,
                       user: User = Depends(require_perm("warehouse.manage")),
                       db: DbSession = Depends(get_db)):
    f = request.state.form_cache
    try:
        services.create_sku(db, user, f.get("code", ""), f.get("name", ""),
                            f.get("description", ""))
        return _done("/manage/skus", "manage.created")
    except ValueError:
        return _done("/manage/skus", "manage.name_taken")


@router.post("/manage/skus/{sid}/update")
def manage_skus_update(sid: int, request: Request,
                       user: User = Depends(require_perm("warehouse.manage")),
                       db: DbSession = Depends(get_db)):
    s = db.get(Sku, sid)
    if s is None:
        return _done("/manage/skus", "error.404")
    f = request.state.form_cache
    services.update_sku(db, user, s, f.get("name", ""), f.get("description", ""))
    return _done("/manage/skus", "manage.updated")


@router.post("/manage/skus/{sid}/active")
def manage_skus_active(sid: int, request: Request,
                       user: User = Depends(require_perm("warehouse.manage")),
                       db: DbSession = Depends(get_db)):
    s = db.get(Sku, sid)
    if s is None:
        return _done("/manage/skus", "error.404")
    active = request.state.form_cache.get("is_active") == "on"
    try:
        services.set_active(db, user, "sku", s, active)
        return _done("/manage/skus", "manage.reactivated" if active else "manage.archived_ok")
    except ValueError:
        return _done("/manage/skus", "manage.has_stock")


# ================= SKU IMPORT (two-phase) =================

@router.get("/manage/skus/import-template")
def skus_import_template(user: User = Depends(require_perm("warehouse.manage"))):
    return Response(
        content=generate_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="sku_import_template.xlsx"'},
    )


@router.get("/manage/skus/import", response_class=HTMLResponse)
def skus_import_page(request: Request, user: User = Depends(require_perm("warehouse.manage"))):
    return templates.TemplateResponse(request, "warehouse/sku_import.html")


@router.post("/manage/skus/import-preview", response_class=HTMLResponse)
def skus_import_preview(request: Request,
                        user: User = Depends(require_perm("warehouse.manage")),
                        db: DbSession = Depends(get_db)):
    file = request.state.form_cache.get("file")
    if not file or not getattr(file, "filename", None):
        return templates.TemplateResponse(request, "warehouse/sku_import.html",
                                          {"error": t("import.error.no_file")})
    content = file.file.read()
    preview = parse_file(content, file.filename)
    if preview.file_error:
        return templates.TemplateResponse(request, "warehouse/sku_import.html",
                                          {"error": preview.file_error})
    preview = validate_against_db(db, preview)
    token = stash_upload(content, file.filename) if preview.valid else None
    return templates.TemplateResponse(request, "warehouse/sku_import_preview.html",
                                      {"preview": preview, "import_token": token})


@router.post("/manage/skus/import-confirm")
def skus_import_confirm(request: Request,
                        user: User = Depends(require_perm("warehouse.manage")),
                        db: DbSession = Depends(get_db)):
    token = request.state.form_cache.get("import_token")
    loaded = load_upload(token)
    if loaded is None:
        return _done("/manage/skus/import", "import.token_invalid")
    content, filename = loaded
    preview = parse_file(content, filename)
    if preview.file_error:
        discard_upload(token)
        return _done("/manage/skus/import", "import.error")
    preview = validate_against_db(db, preview)
    count = commit_import(db, preview.valid, user)
    discard_upload(token)
    return _done("/manage/skus", "import.success" if count else "import.nothing_to_import")


# ================= STOCK OPERATIONS =================

@router.post("/w/stock/request", response_class=HTMLResponse)
def stock_request_create(request: Request, user: User = Depends(require_perm("warehouse.record")),
                         db: DbSession = Depends(get_db)):
    f = request.state.form_cache
    type_ = f.get("type", "")
    if type_ not in ("in", "move", "adjust", "out"):
        return _done("/w", "request.error.invalid")
    try:
        sku_id = int(f.get("sku_id", 0))
        from_r = int(f.get("from_rak_id", 0)) or None
        to_r = int(f.get("to_rak_id", 0)) or None
        qty = int(f.get("qty", 0))
    except (TypeError, ValueError):
        return _done("/w", "request.error.invalid")
    if qty < 0 or (type_ != "adjust" and qty <= 0):
        return _done(f"/w/rak/{to_r or from_r}" if (to_r or from_r) else "/w",
                     "stock.error.qty_must_be_positive")
    back = f"/w/rak/{to_r or from_r}" if (to_r or from_r) else "/w/requests"
    try:
        services.create_stock_request(db, user, type_, sku_id, from_r, to_r, qty,
                                      f.get("reason"))
    except ValueError as e:
        return _done(back, f"request.error.{e.args[0]}")
    return _done(back, "request.created")


@router.post("/manage/stock/execute", response_class=HTMLResponse)
def stock_execute(request: Request, user: User = Depends(require_perm("warehouse.manage")),
                  db: DbSession = Depends(get_db)):
    f = request.state.form_cache
    type_ = f.get("type", "")
    try:
        sku_id = int(f.get("sku_id", 0))
        from_r = int(f.get("from_rak_id", 0)) or None
        to_r = int(f.get("to_rak_id", 0)) or None
        qty = int(f.get("qty", 0))
    except (TypeError, ValueError):
        return _done("/w", "stock.error.invalid_type")
    reason = f.get("reason")
    back = f"/w/rak/{to_r or from_r}" if (to_r or from_r) else "/w"
    try:
        if type_ == "in":
            services.execute_masuk(db, user, sku_id, to_r, qty, reason)
        elif type_ == "move":
            services.execute_pindah(db, user, sku_id, from_r, to_r, qty, reason)
        elif type_ == "adjust":
            services.execute_adjust(db, user, sku_id, to_r or from_r, qty, reason)
        elif type_ == "out":
            services.execute_keluar(db, user, sku_id, from_r, qty, reason)
        else:
            raise ValueError("invalid_type")
        return _done(back, "stock.executed")
    except ValueError as e:
        return _done(back, f"stock.error.{e.args[0]}")


@router.get("/w/requests")
def requests_list(request: Request, user: User = Depends(require_perm("warehouse.view")),
                  db: DbSession = Depends(get_db), page: int = 1, msg: str | None = None):
    stmt = select(StockRequest).order_by(StockRequest.created_at.desc())
    skus = {s.id: s for s in db.scalars(select(Sku)).all()}
    raks = {r.id: r for r in db.scalars(select(Rak)).all()}
    if request.query_params.get("export") == "xlsx":
        rows = [{"Tipe": req.type,
                 "SKU": skus.get(req.sku_id).code if skus.get(req.sku_id) else "",
                 "Dari": raks.get(req.from_rak_id).name
                 if req.from_rak_id and raks.get(req.from_rak_id) else "",
                 "Ke": raks.get(req.to_rak_id).name
                 if req.to_rak_id and raks.get(req.to_rak_id) else "",
                 "Jumlah": req.qty, "Alasan": req.reason or "",
                 "Status": req.status} for req in db.scalars(stmt).all()]
        return export_xlsx(rows, ["Tipe", "SKU", "Dari", "Ke", "Jumlah", "Alasan",
                                  "Status"], "requests.xlsx")
    reqs, pg = paginate(db, stmt, page)
    return templates.TemplateResponse(request, "warehouse/requests.html",
                                      {"reqs": reqs, "skus": skus, "raks": raks,
                                       "pg": pg, "msg": msg})


@router.post("/w/requests/{req_id}/approve")
def request_approve(req_id: int, request: Request,
                    user: User = Depends(require_perm("warehouse.approve")),
                    db: DbSession = Depends(get_db)):
    try:
        services.approve_stock_request(db, user, req_id)
        return _done("/w/requests", "request.approved")
    except ValueError as e:
        return _done("/w/requests", f"request.error.{e.args[0]}")


@router.post("/w/requests/{req_id}/reject")
def request_reject(req_id: int, request: Request,
                   user: User = Depends(require_perm("warehouse.approve")),
                   db: DbSession = Depends(get_db)):
    try:
        services.reject_stock_request(db, user, req_id,
                                      request.state.form_cache.get("review_note"))
        return _done("/w/requests", "request.rejected")
    except ValueError as e:
        return _done("/w/requests", f"request.error.{e.args[0]}")


# ================= SEARCH =================

@router.get("/w/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", page: int = 1,
                user: User = Depends(require_perm("warehouse.view")),
                db: DbSession = Depends(get_db)):
    results = []
    if q.strip():
        term = f"%{q.strip()}%"
        skus = db.scalars(select(Sku).where(
            (Sku.code.ilike(term)) | (Sku.name.ilike(term)),
            Sku.is_active.is_(True),
        ).order_by(Sku.code)).all()
        for sku in skus:
            placements = db.scalars(select(Stock).join(Rak).join(Area).join(Gudang).where(
                Stock.sku_id == sku.id, Stock.qty_boxes > 0, Stock.is_active.is_(True),
                Rak.is_active.is_(True), Area.is_active.is_(True), Gudang.is_active.is_(True),
            )).all()
            for p in placements:
                results.append({"sku": sku, "gudang": p.rak.area.gudang.name,
                                "area": p.rak.area.name, "rak": p.rak.name,
                                "rak_id": p.rak.id, "qty": p.qty_boxes})
    from app.core.pagination import PER_PAGE
    if request.query_params.get("export") == "xlsx":
        rows = [{"SKU": r["sku"].code, "Nama": r["sku"].name, "Gudang": r["gudang"],
                 "Area": r["area"], "Rak": r["rak"], "Jumlah": r["qty"]} for r in results]
        return export_xlsx(rows, ["SKU", "Nama", "Gudang", "Area", "Rak", "Jumlah"],
                           "search.xlsx")
    total = len(results)
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(1, page), pages)
    results = results[(page - 1) * PER_PAGE: page * PER_PAGE]
    pg = {"page": page, "pages": pages, "total": total, "per_page": PER_PAGE}
    return templates.TemplateResponse(request, "warehouse/search.html",
                                      {"q": q, "results": results, "pg": pg})


# ================= QR =================

@router.get("/w/rak/{rid}/qr")
def rak_qr_image(rid: int, user: User = Depends(require_perm("warehouse.view")),
                 db: DbSession = Depends(get_db)):
    r = db.get(Rak, rid)
    if r is None or not r.is_active:
        raise HTTPException(status_code=404)
    return Response(content=generate_qr_png(f"{_qr_base(db)}/w/rak/{r.id}"),
                    media_type="image/png")


@router.get("/w/rak/{rid}/qr-page", response_class=HTMLResponse)
def rak_qr_page(rid: int, request: Request,
                user: User = Depends(require_perm("warehouse.manage")),
                db: DbSession = Depends(get_db)):
    r = db.get(Rak, rid)
    if r is None or not r.is_active:
        raise HTTPException(status_code=404)
    a = db.get(Area, r.area_id)
    g = db.get(Gudang, a.gudang_id)
    return templates.TemplateResponse(request, "warehouse/qr.html", {"r": r, "a": a, "g": g})


@router.get("/w/area/{aid}/qr-sheet", response_class=HTMLResponse)
def area_qr_sheet(aid: int, request: Request,
                  user: User = Depends(require_perm("warehouse.manage")),
                  db: DbSession = Depends(get_db)):
    a = db.get(Area, aid)
    if a is None or not a.is_active:
        raise HTTPException(status_code=404)
    g = db.get(Gudang, a.gudang_id)
    raks = db.scalars(select(Rak).where(Rak.area_id == a.id, Rak.is_active.is_(True))
                      .order_by(Rak.sort_order)).all()
    return templates.TemplateResponse(request, "warehouse/qr_sheet.html",
                                      {"a": a, "g": g, "raks": raks})
