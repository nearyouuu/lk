from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import select, exists
from app.db.session import SessionLocal
from app.core.security import decode_token
from app.services.license_service import has_feature
from app.models.user import User
from app.models.role import Permission, user_roles, role_permissions
from app.models.role import Role

bearer = HTTPBearer()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    token = creds.credentials
    try:
        payload = decode_token(token, expected_type="access")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    subject = payload.get("sub")
    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user

def is_admin(user: User, db: Session) -> bool:
    q = select(exists().where(
        user_roles.c.user_id == user.id
    ).where(
        user_roles.c.role_id == Role.id
    ).where(
        Role.name == "administrator"
    ))
    return bool(db.scalar(q))

def require_admin(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not is_admin(user, db):
        raise HTTPException(status_code=403, detail="Forbidden (admin only)")
    return True

def require_permission(code: str):
    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        # Админ может всё
        if is_admin(user, db):
            return True
        q = (
            select(exists().where(
                Permission.code == code
            ).where(
                role_permissions.c.permission_id == Permission.id
            ).where(
                user_roles.c.role_id == role_permissions.c.role_id
            ).where(
                user_roles.c.user_id == user.id
            ))
        )
        ok = db.scalar(q)
        if not ok:
            raise HTTPException(status_code=403, detail=f"Forbidden: {code}")
        return True
    return checker

def require_role_any(allowed: list[str]):
    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        role_names = db.scalars(
            select(Role.name)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user.id)
        ).all()
        if not any(r in allowed for r in role_names):
            raise HTTPException(status_code=403, detail="Forbidden (role)")
        return True
    return checker


def require_feature(feature: str):
    def checker():
        ok, reason = has_feature(feature)
        if not ok:
            raise HTTPException(
                status_code=403,
                detail=reason or f"Feature '{feature}' is unavailable for the current tariff",
            )
        return True
    return checker
