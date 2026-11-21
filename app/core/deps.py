"""Auth dependencies: current user, permission gates."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.services import permissions_for
from app.core.database import get_db


class LoginRequired(Exception):
    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


def current_user(request: Request):
    return getattr(request.state, "user", None)


def require_perm(*perms: str):
    def dep(request: Request, db: Session = Depends(get_db)):
        user = current_user(request)
        if user is None:
            raise LoginRequired(next_url=request.url.path)
        have = permissions_for(user)
        if not set(perms) <= have:
            raise HTTPException(status_code=403)
        return user
    return dep
