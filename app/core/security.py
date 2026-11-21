"""Password hashing (argon2), session tokens, cookie signing, CSRF tokens."""
from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, URLSafeSerializer

from app.core.config import secret_key

_ph = PasswordHasher()
SID_COOKIE = "_sid"
CSRF_COOKIE = "csrf"
LANG_COOKIE = "lang"
TEN_YEARS = 315360000  # "unlimited" session cookie (CONTEXT.md §5)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False


def make_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _signer() -> URLSafeSerializer:
    return URLSafeSerializer(secret_key(), salt="gudang-sid")


def sign_session_token(token: str) -> str:
    return _signer().dumps(token)


def unsign_session_token(value: str) -> str | None:
    try:
        return _signer().loads(value)
    except BadSignature:
        return None


def make_csrf_token() -> str:
    return secrets.token_urlsafe(32)
