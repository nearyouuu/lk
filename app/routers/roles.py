from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.core.deps import get_db, require_permission
from app.models.role import Role, Permission
from app.schemas.role import RoleCreate, PermissionCreate

router = APIRouter(prefix="/roles", tags=["roles"])

@router.post("", dependencies=[Depends(require_permission("roles:create"))])
def create_role(payload: RoleCreate, db: Session = Depends(get_db)):
    role = Role(name=payload.name, description=payload.description)
    db.add(role); db.commit()
    return {"id": role.id, "name": role.name}

@router.post("/{role_id}/permissions", dependencies=[Depends(require_permission("roles:assign_permissions"))])
def add_permission(role_id: int, payload: PermissionCreate, db: Session = Depends(get_db)):
    perm = db.scalar(select(Permission).where(Permission.code == payload.code))
    if not perm:
        perm = Permission(code=payload.code, description=payload.description)
        db.add(perm); db.flush()
    r = db.get(Role, role_id)
    r.permissions.append(perm)
    db.commit()
    return {"role_id": role_id, "permission": payload.code}
