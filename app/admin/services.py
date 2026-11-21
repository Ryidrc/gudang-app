"""Dashboard aggregate stats (shared by / and /admin/)."""
from __future__ import annotations

from sqlalchemy import func, select

from app.auth.models import FailedLogin
from app.warehouse.models import Sku, Stock, StockRequest


def dashboard_stats(db, user) -> dict:
    active_skus = db.scalar(select(func.count(Sku.id)).where(Sku.is_active.is_(True))) or 0
    total_boxes = db.scalar(select(func.coalesce(func.sum(Stock.qty_boxes), 0)).where(
        Stock.qty_boxes > 0, Stock.is_active.is_(True))) or 0
    if user.role in ("owner", "manager"):
        pending_reqs = db.scalar(select(func.count(StockRequest.id)).where(
            StockRequest.status == "pending")) or 0
        failed_24h = db.scalar(select(func.count(FailedLogin.id)).where(
            FailedLogin.created_at >= func.datetime("now", "-1 day"))) or 0
    else:
        pending_reqs = db.scalar(select(func.count(StockRequest.id)).where(
            StockRequest.status == "pending", StockRequest.requested_by == user.id)) or 0
        failed_24h = 0
    return {"active_skus": active_skus, "total_boxes": total_boxes,
            "pending_reqs": pending_reqs, "failed_24h": failed_24h}
