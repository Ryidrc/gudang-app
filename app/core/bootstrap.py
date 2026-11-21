"""CLI: create the first Owner. Refuses if any owner exists."""
from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from app.auth.models import User
from app.core.database import SessionLocal
from app.core.models import write_audit
from app.core.security import hash_password


def owner_exists(db) -> bool:
    return db.scalar(select(User.id).where(User.role == "owner")) is not None


def create_owner(db, username: str, display_name: str, password: str) -> User:
    user = User(username=username.strip().lower(), display_name=display_name.strip(),
                password_hash=hash_password(password), role="owner",
                can_record=False, is_active=True)
    db.add(user)
    db.flush()
    write_audit(db, None, "bootstrap.owner", "user", user.id,
                after={"username": user.username})
    db.commit()
    return user


def main() -> int:
    db = SessionLocal()
    try:
        if owner_exists(db):
            print("[bootstrap] An Owner already exists. Refusing to create another here.")
            print("[bootstrap] Use the admin UI (Owner login) to add more Owners.")
            return 1
        username = input("Username: ").strip()
        display = input("Display name: ").strip() or username
        pw = getpass.getpass("Password: ")
        pw2 = getpass.getpass("Confirm password: ")
        if not username or len(pw) < 8:
            print("[bootstrap] Username required; password must be >= 8 chars.")
            return 1
        if pw != pw2:
            print("[bootstrap] Passwords do not match.")
            return 1
        create_owner(db, username, display, pw)
        print(f"[bootstrap] Owner '{username.lower()}' created. Log in at http://localhost:8000")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
