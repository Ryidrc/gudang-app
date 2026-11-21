"""Warehouse tree + stock placement models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models import AuditMixin, Base, CreatedAtMixin, IdMixin


class Gudang(IdMixin, CreatedAtMixin, AuditMixin, Base):
    __tablename__ = "gudangs"
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    areas: Mapped[list["Area"]] = relationship(back_populates="gudang")


class Area(IdMixin, CreatedAtMixin, AuditMixin, Base):
    __tablename__ = "areas"
    gudang_id: Mapped[int] = mapped_column(ForeignKey("gudangs.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    layout: Mapped[str] = mapped_column(String(10), default="vertical")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("gudang_id", "name", name="uq_areas_gudang_name"),)

    gudang: Mapped["Gudang"] = relationship(back_populates="areas")
    raks: Mapped[list["Rak"]] = relationship(back_populates="area")


class Rak(IdMixin, CreatedAtMixin, AuditMixin, Base):
    __tablename__ = "raks"
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("area_id", "name", name="uq_raks_area_name"),)

    area: Mapped["Area"] = relationship(back_populates="raks")
    stocks: Mapped[list["Stock"]] = relationship(back_populates="rak")


class Sku(IdMixin, CreatedAtMixin, AuditMixin, Base):
    __tablename__ = "skus"
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    stocks: Mapped[list["Stock"]] = relationship(back_populates="sku")


class Stock(IdMixin, AuditMixin, Base):
    __tablename__ = "stocks"
    rak_id: Mapped[int] = mapped_column(ForeignKey("raks.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), index=True)
    qty_boxes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("rak_id", "sku_id", name="uq_stocks_rak_sku"),)

    rak: Mapped["Rak"] = relationship(back_populates="stocks")
    sku: Mapped["Sku"] = relationship(back_populates="stocks")


# --- Stock Engine Models (from I4) ---

class StockEvent(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "stock_events"
    type: Mapped[str] = mapped_column(String(10), index=True)  # in, move, adjust, out
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), index=True)
    from_rak_id: Mapped[int | None] = mapped_column(ForeignKey("raks.id"), nullable=True)
    to_rak_id: Mapped[int | None] = mapped_column(ForeignKey("raks.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("stock_requests.id"), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class StockRequest(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "stock_requests"
    type: Mapped[str] = mapped_column(String(10), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), index=True)
    from_rak_id: Mapped[int | None] = mapped_column(ForeignKey("raks.id"), nullable=True)
    to_rak_id: Mapped[int | None] = mapped_column(ForeignKey("raks.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
