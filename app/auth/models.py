"""Auth models: users, sessions, failed logins."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import AuditMixin, Base, CreatedAtMixin, IdMixin


class User(IdMixin, CreatedAtMixin, AuditMixin, Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), index=True)  # owner|manager|staff
    can_record: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Session(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "sessions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(45))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)  # always NULL
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class FailedLogin(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "failed_logins"
    username: Mapped[str] = mapped_column(String(64), index=True)
    ip: Mapped[str | None] = mapped_column(String(45))
