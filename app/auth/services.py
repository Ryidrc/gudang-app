"""Auth business logic: permissions, sessions, user admin with scoping."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from app.auth.models import FailedLogin, Session, User
from app.core.models import utcnow, write_audit
from app.core.security import (hash_password, make_token, token_hash,
                               verify_password)

PERMISSIONS = (
    "warehouse.view", "warehouse.record", "warehouse.approve", "warehouse.manage",
    "admin.users", "admin.audit", "admin.settings", "admin.backup",
)
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "owner": set(PERMISSIONS),
    # PRD §2: Manager = warehouse.* + admin.audit. User management is Owner-only.
    "manager": {"warehouse.view", "warehouse.record", "warehouse.approve",
                "warehouse.manage", "admin.audit"},
    "staff": {"warehouse.view"},
}


def permissions_for(user: User) -> set[str]:
    perms = set(ROLE_PERMISSIONS.get(user.role, set()))
    if user.role == "staff" and user.can_record:
        perms.add("warehouse.record")
    return perms


def can_manage_user(actor: User, target: User) -> bool:
    if actor is None or target is None or actor.id == target.id:
        return False
    if actor.role == "owner":
        return True
    if actor.role == "manager":
        return target.role in ("manager", "staff")
    return False


def creatable_roles(actor: User) -> set[str]:
    if actor.role == "owner":
        return {"owner", "manager", "staff"}
    if actor.role == "manager":
        return {"manager", "staff"}
    return set()


# ---------- login / failures ----------

def authenticate(db: DbSession, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None
    return user


def record_failed_login(db: DbSession, username: str, ip: str | None) -> None:
    username = username.strip().lower()
    db.add(FailedLogin(username=username, ip=ip))
    write_audit(db, None, "auth.login_failed", "user", None,
                after={"username": username})
    cutoff = utcnow() - timedelta(hours=24)
    db.execute(delete(FailedLogin).where(FailedLogin.created_at < cutoff))
    db.commit()


def failed_login_count_24h(db: DbSession) -> int:
    cutoff = utcnow() - timedelta(hours=24)
    return db.scalar(select(func.count(FailedLogin.id)).where(
        FailedLogin.created_at >= cutoff)) or 0


# ---------- sessions ----------

def create_session(db: DbSession, user: User, user_agent: str | None,
                   ip: str | None) -> Session:
    token = make_token()
    row = Session(user_id=user.id, token_hash=token_hash(token),
                  user_agent=(user_agent or "")[:255], ip=ip,
                  last_seen_at=utcnow(), expires_at=None, revoked_at=None)
    db.add(row)
    db.flush()
    row.token_plain = token  # transient attribute for the route layer
    return row


def resolve_session(db: DbSession, signed: str, user_agent: str | None = None,
                    ip: str | None = None) -> tuple[User, Session] | None:
    from app.core.security import unsign_session_token
    token = unsign_session_token(signed)
    if token is None:
        return None
    row = db.scalar(select(Session).where(Session.token_hash == token_hash(token),
                                          Session.revoked_at.is_(None)))
    if row is None:
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    now = utcnow()
    if row.last_seen_at is None or (now - row.last_seen_at) > timedelta(seconds=60):
        row.last_seen_at = now
        db.commit()
    return user, row


def revoke_session(db: DbSession, row: Session) -> None:
    row.revoked_at = utcnow()
    db.commit()


def revoke_all_sessions(db: DbSession, user_id: int) -> int:
    now = utcnow()
    rows = db.scalars(select(Session).where(Session.user_id == user_id,
                                            Session.revoked_at.is_(None))).all()
    for r in rows:
        r.revoked_at = now
    db.commit()
    return len(rows)


# ---------- user admin ----------

def _norm_username(username: str) -> str:
    return username.strip().lower()


def create_user(db: DbSession, actor: User, username: str, display_name: str,
                password: str, role: str, can_record: bool) -> User:
    uname = _norm_username(username)
    if role not in creatable_roles(actor):
        raise ValueError("role_not_allowed")
    if len(password) < 8:
        raise ValueError("weak_password")
    if db.scalar(select(User.id).where(User.username == uname)):
        raise ValueError("username_taken")
    user = User(username=uname, display_name=display_name.strip(),
                password_hash=hash_password(password), role=role,
                can_record=bool(can_record) and role == "staff", is_active=True)
    db.add(user)
    db.flush()
    write_audit(db, actor, "user.create", "user", user.id,
                after={"username": uname, "role": role})
    db.commit()
    return user


def update_user(db: DbSession, actor: User, target: User, display_name: str | None,
                role: str | None, can_record: bool | None,
                is_active: bool | None) -> User:
    if not can_manage_user(actor, target):
        raise ValueError("denied")
    before = {"display_name": target.display_name, "role": target.role,
              "can_record": target.can_record, "is_active": target.is_active}
    if display_name is not None:
        target.display_name = display_name.strip()
    if role is not None and role != target.role:
        if role not in creatable_roles(actor):
            raise ValueError("role_not_allowed")
        target.role = role
        if role != "staff":
            target.can_record = False
    if can_record is not None and target.role == "staff":
        target.can_record = bool(can_record)
    if is_active is not None and target.is_active != bool(is_active):
        target.is_active = bool(is_active)
        if not target.is_active:
            revoke_all_sessions(db, target.id)
    write_audit(db, actor, "user.update", "user", target.id, before=before,
                after={"display_name": target.display_name, "role": target.role,
                       "can_record": target.can_record,
                       "is_active": target.is_active})
    db.commit()
    return target


def admin_set_password(db: DbSession, actor: User, target: User,
                       new_password: str) -> None:
    if not can_manage_user(actor, target):
        raise ValueError("denied")
    if len(new_password) < 8:
        raise ValueError("weak_password")
    target.password_hash = hash_password(new_password)
    target.must_change_password = True
    write_audit(db, actor, "user.reset_password", "user", target.id)
    db.commit()
    revoke_all_sessions(db, target.id)


def change_own_password(db: DbSession, user: User, current: str,
                        new_password: str) -> bool:
    if not verify_password(current, user.password_hash):
        return False
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    write_audit(db, user, "user.change_password", "user", user.id)
    db.commit()
    # revoke every session except the current one is handled by route layer
    return True
