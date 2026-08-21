from pydantic import BaseModel

class RoleCreate(BaseModel):
    name: str
    description: str | None = None

class PermissionCreate(BaseModel):
    code: str
    description: str | None = None
