from __future__ import annotations
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, field_validator

MaterialType = Literal[
    "document", "video", "link", "presentation", "other"
]

class MaterialBase(BaseModel):
    """Общие поля для создания и обновления материалов."""
    title: str
    description: Optional[str] = None
    type: MaterialType = "document"

    subject_id: int
    subject_code: str | None = None
    group_id: int
    link: Optional[str] = None
    text_content: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Поле 'title' не может быть пустым")
        return v

class MaterialCreate(MaterialBase):
    """Схема для POST-запросов при создании материала.
    Файл передаётся как UploadFile в роутере, не в схеме."""
    pass

class MaterialUpdate(BaseModel):
    """Схема для PATCH-запросов (частичное обновление)."""
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[MaterialType] = None
    link: Optional[str] = None
    text_content: Optional[str] = None
    is_published: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v


class MaterialOut(MaterialBase):
    """Полный объект для ответа API."""
    id: int
    teacher_id: int
    is_published: bool
    created_at: datetime
    updated_at: datetime
    file_path: Optional[str] = None

    class Config:
        from_attributes = True
