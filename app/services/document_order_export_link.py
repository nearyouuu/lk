from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt

from app.core.config import settings


EXPORT_TOKEN_TYPE = "document_order_book_export"


def create_export_link_token(
    filters: dict,
    creator_id: int,
    expires_in_hours: int,
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=expires_in_hours)
    payload = {
        "sub": str(creator_id),
        "type": EXPORT_TOKEN_TYPE,
        "filters": filters,
        "iat": now,
        "exp": expires_at,
        "jti": uuid4().hex,
    }
    token = jwt.encode(
        payload,
        settings.EXPORT_LINK_SECRET,
        algorithm=settings.JWT_ALG,
    )
    return token, expires_at


def decode_export_link_token(token: str) -> dict:
    payload = jwt.decode(
        token,
        settings.EXPORT_LINK_SECRET,
        algorithms=[settings.JWT_ALG],
    )
    if payload.get("type") != EXPORT_TOKEN_TYPE or not isinstance(payload.get("filters"), dict):
        raise jwt.InvalidTokenError("Invalid export token")
    return payload
