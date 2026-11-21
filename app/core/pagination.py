"""Shared pagination for list views (>50 rows)."""
from __future__ import annotations

import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

PER_PAGE = 50


def paginate(db: Session, stmt, page: int = 1, per_page: int = PER_PAGE):
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    pages = max(1, math.ceil(total / per_page))
    page = min(max(1, page), pages)
    items = db.scalars(stmt.limit(per_page).offset((page - 1) * per_page)).all()
    return items, {"page": page, "pages": pages, "total": total, "per_page": per_page}
