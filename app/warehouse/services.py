"""Warehouse tree business logic: CRUD, archive semantics, stock-presence checks."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.core.models import write_audit
from app.warehouse.models import Area, Gudang, Rak, Sku, Stock

LAYOUTS = ("horizontal", "vertical")


def _snap(obj) -> dict:
    return {c: getattr(obj, c) for c in obj.__table__.columns.keys()}


# ---------- stock presence (archive guards) ----------

def has_stock(db: DbSession, kind: str, obj_id: int) -> bool:
    if kind == "rak":
        q = select(Stock.id).where(Stock.rak_id == obj_id, Stock.qty_boxes > 0)
    elif kind == "area":
        q = select(Stock.id).join(Rak, Rak.id == Stock.rak_id).where(
            Rak.area_id == obj_id, Stock.qty_boxes > 0)
    elif kind == "gudang":
        q = select(Stock.id).join(Rak, Rak.id == Stock.rak_id).join(
            Area, Area.id == Rak.area_id).where(
            Area.gudang_id == obj_id, Stock.qty_boxes > 0)
    elif kind == "sku":
        q = select(Stock.id).where(Stock.sku_id == obj_id, Stock.qty_boxes > 0)
    else:
        raise ValueError("unknown kind")
    return db.scalar(q.limit(1)) is not None


def set_active(db: DbSession, actor, kind: str, obj, active: bool) -> None:
    if not active and has_stock(db, kind, obj.id):
        raise ValueError("has_stock")
    before = _snap(obj)
    obj.is_active = active
    write_audit(db, actor, f"{kind}.{'reactivate' if active else 'archive'}",
                kind, obj.id, before=before, after=_snap(obj))
    db.commit()


# ---------- gudang ----------

def create_gudang(db: DbSession, actor, name: str) -> Gudang:
    g = Gudang(name=name.strip())
    if not g.name:
        raise ValueError("empty")
    db.add(g)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("name_taken")
    write_audit(db, actor, "gudang.create", "gudang", g.id, after=_snap(g))
    db.commit()
    return g


def update_gudang(db: DbSession, actor, g: Gudang, name: str) -> Gudang:
    before = _snap(g)
    g.name = name.strip() or g.name
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("name_taken")
    write_audit(db, actor, "gudang.update", "gudang", g.id, before=before, after=_snap(g))
    db.commit()
    return g


# ---------- area ----------

def create_area(db: DbSession, actor, gudang_id: int, name: str,
                sort_order: int) -> Area:
    a = Area(gudang_id=gudang_id, name=name.strip(),
             sort_order=int(sort_order or 0))
    if not a.name:
        raise ValueError("empty")
    db.add(a)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("name_taken")
    write_audit(db, actor, "area.create", "area", a.id, after=_snap(a))
    db.commit()
    return a


def update_area(db: DbSession, actor, a: Area, name: str,
                sort_order: int) -> Area:
    before = _snap(a)
    a.name = name.strip() or a.name
    a.sort_order = int(sort_order or 0)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("name_taken")
    write_audit(db, actor, "area.update", "area", a.id, before=before, after=_snap(a))
    db.commit()
    return a


# ---------- rak ----------

def create_rak(db: DbSession, actor, area_id: int, name: str, sort_order: int) -> Rak:
    r = Rak(area_id=area_id, name=name.strip(), sort_order=int(sort_order or 0))
    if not r.name:
        raise ValueError("empty")
    db.add(r)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("name_taken")
    write_audit(db, actor, "rak.create", "rak", r.id, after=_snap(r))
    db.commit()
    return r


def update_rak(db: DbSession, actor, r: Rak, name: str, sort_order: int) -> Rak:
    before = _snap(r)
    r.name = name.strip() or r.name
    r.sort_order = int(sort_order or 0)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("name_taken")
    write_audit(db, actor, "rak.update", "rak", r.id, before=before, after=_snap(r))
    db.commit()
    return r


# ---------- sku ----------

def create_sku(db: DbSession, actor, code: str, name: str,
               description: str | None) -> Sku:
    s = Sku(code=code.strip().upper(), name=name.strip(),
            description=description or None)
    if not s.code or not s.name:
        raise ValueError("empty")
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("name_taken")
    write_audit(db, actor, "sku.create", "sku", s.id, after=_snap(s))
    db.commit()
    return s


def update_sku(db: DbSession, actor, s: Sku, name: str,
               description: str | None) -> Sku:
    """SKU code is IMMUTABLE — never updated here (PRD Q8)."""
    before = _snap(s)
    s.name = name.strip() or s.name
    s.description = description or None
    write_audit(db, actor, "sku.update", "sku", s.id, before=before, after=_snap(s))
    db.commit()
    return s

from app.core.models import utcnow
from app.warehouse.models import StockEvent, StockRequest

def get_or_create_stock(db: DbSession, rak_id: int, sku_id: int) -> Stock:
    stock = db.scalar(select(Stock).where(Stock.rak_id == rak_id, Stock.sku_id == sku_id))
    if stock is None:
        stock = Stock(rak_id=rak_id, sku_id=sku_id, qty_boxes=0, is_active=True)
        db.add(stock)
        db.flush()
    return stock


def _record_event(db: DbSession, actor, type_: str, sku_id: int, from_rak_id: int | None,
                  to_rak_id: int | None, qty: int, reason: str | None, request_id: int | None):
    db.add(StockEvent(
        type=type_, sku_id=sku_id, from_rak_id=from_rak_id, to_rak_id=to_rak_id,
        qty=qty, reason=reason, request_id=request_id, actor_id=actor.id if actor else None
    ))


def execute_masuk(db: DbSession, actor, sku_id: int, rak_id: int, qty: int,
                  reason: str | None, request_id: int | None = None, commit: bool = True):
    if qty <= 0: raise ValueError("qty_must_be_positive")
    stock = get_or_create_stock(db, rak_id, sku_id)
    stock.qty_boxes += qty
    stock.is_active = True
    _record_event(db, actor, "in", sku_id, None, rak_id, qty, reason, request_id)
    write_audit(db, actor, "stock.masuk", "stock", stock.id, after={"qty": stock.qty_boxes})
    if commit: db.commit()


def execute_pindah(db: DbSession, actor, sku_id: int, from_rak_id: int, to_rak_id: int,
                   qty: int, reason: str | None, request_id: int | None = None,
                   commit: bool = True):
    if qty <= 0: raise ValueError("qty_must_be_positive")
    if from_rak_id == to_rak_id: raise ValueError("same_rak")
    from_stock = db.scalar(select(Stock).where(Stock.rak_id == from_rak_id, Stock.sku_id == sku_id))
    if from_stock is None or from_stock.qty_boxes < qty: raise ValueError("insufficient_stock")

    from_stock.qty_boxes -= qty
    if from_stock.qty_boxes == 0: from_stock.is_active = False

    to_stock = get_or_create_stock(db, to_rak_id, sku_id)
    to_stock.qty_boxes += qty
    to_stock.is_active = True

    _record_event(db, actor, "move", sku_id, from_rak_id, to_rak_id, qty, reason, request_id)
    write_audit(db, actor, "stock.pindah", "stock", to_stock.id,
                before={"from_qty": from_stock.qty_boxes + qty, "to_qty": to_stock.qty_boxes - qty},
                after={"from_qty": from_stock.qty_boxes, "to_qty": to_stock.qty_boxes})
    if commit: db.commit()


def execute_adjust(db: DbSession, actor, sku_id: int, rak_id: int, target_qty: int,
                   reason: str | None, request_id: int | None = None, commit: bool = True):
    if target_qty < 0: raise ValueError("qty_cannot_be_negative")
    stock = get_or_create_stock(db, rak_id, sku_id)
    delta = target_qty - stock.qty_boxes
    if delta == 0:
        return
    stock.qty_boxes = target_qty
    stock.is_active = target_qty > 0
    _record_event(db, actor, "adjust", sku_id, rak_id, rak_id, delta, reason, request_id)
    write_audit(db, actor, "stock.adjust", "stock", stock.id,
                before={"qty": stock.qty_boxes - delta}, after={"qty": stock.qty_boxes})
    if commit: db.commit()


def execute_keluar(db: DbSession, actor, sku_id: int, rak_id: int, qty: int,
                   reason: str | None, request_id: int | None = None, commit: bool = True):
    if qty <= 0: raise ValueError("qty_must_be_positive")
    if not reason: raise ValueError("reason_required")
    stock = db.scalar(select(Stock).where(Stock.rak_id == rak_id, Stock.sku_id == sku_id))
    if stock is None or stock.qty_boxes < qty: raise ValueError("insufficient_stock")

    stock.qty_boxes -= qty
    if stock.qty_boxes == 0: stock.is_active = False

    _record_event(db, actor, "out", sku_id, rak_id, None, qty, reason, request_id)
    write_audit(db, actor, "stock.keluar", "stock", stock.id,
                before={"qty": stock.qty_boxes + qty}, after={"qty": stock.qty_boxes})
    if commit: db.commit()


def batch_apply_stock(db: DbSession, actor, mode: str,
                      entries: list[tuple[int, int, int]],
                      reason: str | None) -> int:
    """Apply stock changes for many (sku, rak) pairs in one transaction."""
    if mode not in ("adjust", "in", "out"):
        raise ValueError("invalid_type")
    if mode == "out" and not (reason or "").strip():
        raise ValueError("reason_required")

    seen: set[tuple[int, int]] = set()
    for sku_id, rak_id, _qty in entries:
        pair = (sku_id, rak_id)
        if pair in seen:
            raise ValueError("batch_duplicate")
        seen.add(pair)

    for _sku_id, _rak_id, qty in entries:
        if qty < 0:
            raise ValueError("qty_cannot_be_negative")

    sku_ids = {sku_id for sku_id, _rak_id, _qty in entries}
    if sku_ids:
        active_skus = set(db.scalars(
            select(Sku.id).where(Sku.id.in_(sku_ids), Sku.is_active.is_(True))))
        if active_skus != sku_ids:
            raise ValueError("batch_invalid_sku")

    rak_ids = {rak_id for _sku_id, rak_id, _qty in entries}
    if rak_ids:
        active_raks = set(db.scalars(
            select(Rak.id)
            .join(Area, Area.id == Rak.area_id)
            .join(Gudang, Gudang.id == Area.gudang_id)
            .where(Rak.is_active.is_(True), Area.is_active.is_(True),
                   Gudang.is_active.is_(True))))
        if not rak_ids <= active_raks:
            raise ValueError("invalid_rak")

    if mode == "out":
        for sku_id, rak_id, qty in entries:
            if qty <= 0:
                continue
            stock = db.scalar(select(Stock).where(
                Stock.rak_id == rak_id, Stock.sku_id == sku_id))
            if stock is None or stock.qty_boxes < qty:
                raise ValueError("insufficient_stock")

    changed = 0
    try:
        for sku_id, rak_id, qty in entries:
            if mode == "in":
                if qty == 0:
                    continue
                execute_masuk(db, actor, sku_id, rak_id, qty, reason, commit=False)
                changed += 1
            elif mode == "out":
                if qty == 0:
                    continue
                execute_keluar(db, actor, sku_id, rak_id, qty, reason, commit=False)
                changed += 1
            else:
                stock = db.scalar(select(Stock).where(
                    Stock.rak_id == rak_id, Stock.sku_id == sku_id))
                if (stock.qty_boxes if stock is not None else 0) == qty:
                    continue
                execute_adjust(db, actor, sku_id, rak_id, qty, reason, commit=False)
                changed += 1
        if changed:
            db.commit()
    except ValueError:
        db.rollback()
        raise
    return changed


def create_stock_request(db: DbSession, actor, type_: str, sku_id: int,
                         from_rak_id: int | None, to_rak_id: int | None,
                         qty: int, reason: str | None) -> StockRequest:
    req = StockRequest(type=type_, sku_id=sku_id, from_rak_id=from_rak_id, to_rak_id=to_rak_id,
                       qty=qty, reason=reason, status="pending", requested_by=actor.id)
    db.add(req)
    write_audit(db, actor, "request.create", "stock_request", req.id, after={"type": type_, "qty": qty})
    db.commit()
    return req


def approve_stock_request(db: DbSession, actor, req_id: int):
    req = db.get(StockRequest, req_id)
    if req is None or req.status != "pending": raise ValueError("request_not_pending")

    if req.type in ("move", "out") and req.from_rak_id:
        from_stock = db.scalar(select(Stock).where(Stock.rak_id == req.from_rak_id, Stock.sku_id == req.sku_id))
        if from_stock is None or from_stock.qty_boxes < req.qty:
            req.status = "rejected"
            req.reviewed_by = actor.id
            req.reviewed_at = utcnow()
            req.review_note = "Stok tidak cukup saat disetujui"  # data, not UI copy
            write_audit(db, actor, "request.auto_reject", "stock_request", req.id)
            db.commit()
            raise ValueError("insufficient_stock_at_approval")

    # One transaction: stock change + request status commit together or not at all.
    rak_id = req.to_rak_id or req.from_rak_id
    kwargs = {"commit": False}
    if req.type == "in":
        execute_masuk(db, actor, req.sku_id, rak_id, req.qty, req.reason, req.id, **kwargs)
    elif req.type == "move":
        execute_pindah(db, actor, req.sku_id, req.from_rak_id, req.to_rak_id, req.qty,
                       req.reason, req.id, **kwargs)
    elif req.type == "adjust":
        execute_adjust(db, actor, req.sku_id, rak_id, req.qty, req.reason, req.id, **kwargs)
    elif req.type == "out":
        execute_keluar(db, actor, req.sku_id, req.from_rak_id, req.qty, req.reason,
                       req.id, **kwargs)
    else:
        raise ValueError("invalid_type")

    req.status = "approved"
    req.reviewed_by = actor.id
    req.reviewed_at = utcnow()
    write_audit(db, actor, "request.approve", "stock_request", req.id)
    db.commit()


def reject_stock_request(db: DbSession, actor, req_id: int, note: str | None):
    req = db.get(StockRequest, req_id)
    if req is None or req.status != "pending": raise ValueError("request_not_pending")
    req.status = "rejected"
    req.reviewed_by = actor.id
    req.reviewed_at = utcnow()
    req.review_note = note
    write_audit(db, actor, "request.reject", "stock_request", req.id)
    db.commit()
