import os

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite://"

from app.core.security import create_access_token, create_refresh_token, decode_token
from app.db.base import Base
# Register all related SQLAlchemy models before User mappers are configured.
from app.models import achievement, application, audit, document_order, material, news, profile, role, subject_type, testing  # noqa: F401, E501
from app.models import grade, schedule  # noqa: F401
from app.models.user import User
from app.routers.auth import refresh
from app.schemas.auth import RefreshTokenIn


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_access_and_refresh_tokens_have_distinct_types():
    access_token = create_access_token("42")
    refresh_token = create_refresh_token("42")

    assert decode_token(access_token, expected_type="access")["sub"] == "42"
    assert decode_token(refresh_token, expected_type="refresh")["sub"] == "42"

    with pytest.raises(jwt.InvalidTokenError):
        decode_token(refresh_token, expected_type="access")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(access_token, expected_type="refresh")


def test_refresh_rotates_token_pair_for_active_user():
    engine, db = _db()
    try:
        user = User(email="refresh@test.kz", password_hash="hash", is_active=True)
        db.add(user)
        db.commit()

        old_refresh = create_refresh_token(str(user.id))
        result = refresh(RefreshTokenIn(refresh_token=old_refresh), db)

        assert result.access_token
        assert result.refresh_token
        assert result.refresh_token != old_refresh
        assert decode_token(result.access_token, expected_type="access")["sub"] == str(user.id)
        assert decode_token(result.refresh_token, expected_type="refresh")["sub"] == str(user.id)
    finally:
        db.close()
        engine.dispose()


def test_access_token_cannot_be_used_for_refresh():
    engine, db = _db()
    try:
        with pytest.raises(HTTPException) as exc_info:
            refresh(RefreshTokenIn(refresh_token=create_access_token("1")), db)
        assert exc_info.value.status_code == 401
    finally:
        db.close()
        engine.dispose()
