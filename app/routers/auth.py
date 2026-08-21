from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from datetime import datetime, timezone
import jwt

from app.core.deps import get_db
from app.core.config import settings
from app.core.security import (
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
)
from app.schemas.auth import LoginIn, RefreshTokenIn, TokenOut
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_token_pair(user: User) -> TokenOut:
    subject = str(user.id)
    return TokenOut(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
        expires_in=settings.ACCESS_TOKEN_EXPIRES_MIN * 60,
    )

@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash) or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    return _issue_token_pair(user)

@router.post("/register", response_model=TokenOut)
def register(payload: LoginIn, db: Session = Depends(get_db)):
    exists = db.scalar(select(User).where(User.email == payload.email))
    if exists:
        raise HTTPException(status_code=400, detail="Email in use")
    user = User(email=payload.email, password_hash=hash_password(payload.password), is_active=True)
    db.add(user); db.commit()
    return _issue_token_pair(user)


@router.post("/refresh", response_model=TokenOut)
def refresh(payload: RefreshTokenIn, db: Session = Depends(get_db)):
    try:
        token_payload = decode_token(payload.refresh_token, expected_type="refresh")
        user_id = int(token_payload.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Return a fresh pair so the client can replace both stored tokens at once.
    return _issue_token_pair(user)
