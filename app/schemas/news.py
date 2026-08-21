from pydantic import BaseModel
from datetime import datetime

class TagCreate(BaseModel):
    name: str


class TagOut(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True


class NewsCreate(BaseModel):
    title: str
    body: str
    publish: bool = False
    tag_ids: list[int] | None = None 


class NewsUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    publish: bool | None = None
    tag_ids: list[int] | None = None


class NewsOut(BaseModel):
    id: int
    body: str
    title: str
    published_at: datetime | None
    author_name: str | None = None
    photo_url: str | None = None
    tags: list[TagOut] | None = None

    class Config:
        orm_mode = True

class NewsDetailOut(BaseModel):
    id: int
    title: str
    body: str
    author_name: str | None
    is_published: bool
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    photo_url: str | None = None
    tags: list[TagOut] | None = None

    class Config:
        orm_mode = True
