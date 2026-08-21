from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, delete
from app.core.deps import get_db, get_current_user, require_permission, is_admin
from app.core.security import hash_password
from app.models.user import User
from app.models.role import Role, user_roles
from app.models.grade import Student
from app.models.schedule import Group, Teacher
from app.models.profile import AdminProfile, Director
from app.schemas.user import UserCreate, UserOut, MeOut, MeAdmin, MeDirector, MeTeacher, MeStudent

router = APIRouter(prefix="/users", tags=["users"])

def _get_role(db: Session, name: str) -> Role:
    r = db.scalar(select(Role).where(Role.name == name))
    if not r:
        raise HTTPException(status_code=400, detail=f"Role not found: {name}")
    return r

def _target_has_admin(db: Session, user_id: int) -> bool:
    q = select(Role.name).join(user_roles, user_roles.c.role_id == Role.id).where(user_roles.c.user_id == user_id)
    return any(name == "administrator" for name in db.scalars(q).all())

@router.post("", response_model=UserOut,
             dependencies=[Depends(require_permission("users:create"))])
def create_user(payload: UserCreate, me=Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=400, detail="Email already exists")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        birth_date=payload.birth_date,
        avatar_url=payload.avatar_url,
        is_active=True
    )
    db.add(user); db.flush()
    role = _get_role(db, payload.role)
    db.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))

    if payload.role == "administrator":
        db.add(AdminProfile(user_id=user.id, subject=None))
    elif payload.role == "director":
        db.add(Director(user_id=user.id, full_name=user.full_name or "", email=user.email, phone=user.phone, subject=None))
    elif payload.role == "teacher":
        db.add(Teacher(user_id=user.id, full_name=user.full_name or "", email=user.email, phone=user.phone, subject=None))
    elif payload.role == "student":
        db.add(Student(user_id=user.id, group_id=0, record_book=None, insert_year=None, course=None))

    db.commit()
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, is_active=user.is_active, last_login=user.last_login)

@router.post("/{user_id}", dependencies=[Depends(require_permission("users:delete"))])
def delete_user(user_id: int, me=Depends(get_current_user), db: Session = Depends(get_db)):
    actor_is_admin = is_admin(me, db)
    if not actor_is_admin and _target_has_admin(db, user_id):
        raise HTTPException(status_code=403, detail="Directors can't modify administrators")
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    db.execute(delete(User).where(User.id == user_id))
    db.commit()
    return {"deleted": user_id}

@router.get("", response_model=list[UserOut], dependencies=[Depends(require_permission("users:read"))])
def list_users(db: Session = Depends(get_db), q: str | None = Query(None)):
    stmt = select(User)
    if q:
        stmt = stmt.where(User.full_name.ilike(f"%{q}%"))
    rows = db.scalars(stmt).all()
    return [
    UserOut(id=u.id, email=u.email, full_name=u.full_name, is_active=u.is_active, last_login=u.last_login)
    for u in rows
]
