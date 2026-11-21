"""Test configuration and fixtures."""
import os

os.environ["GUDANG_TEST"] = "1"  # must be set before app import: disables APScheduler

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import database as db_module
from app.core.database import get_db
from app.core.models import Base
from app.core.security import hash_password
from app.auth.models import User
from app.main import app


@pytest.fixture(scope="function")
def db(tmp_path):
    """Fresh file-backed SQLite DB per test (isolated, real WAL-free schema)."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        yield db

    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    app.dependency_overrides[get_db] = override_get_db
    original_session_local = db_module.SessionLocal
    db_module.SessionLocal = factory

    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    db_module.SessionLocal = original_session_local


def make_user(db, username: str, role: str, can_record: bool = False,
              is_active: bool = True):
    user = User(
        username=username,
        display_name=username.capitalize(),
        password_hash=hash_password("password123"),
        role=role,
        can_record=can_record,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login(client: TestClient, username: str, password: str = "password123"):
    client.get("/login")
    csrf = client.cookies.get("csrf")
    return client.post(
        "/login",
        data={
            "csrf_token": csrf,
            "username": username,
            "password": password,
            "next": "/",
        },
        follow_redirects=False,
    )
