from datetime import datetime
from sqlalchemy import (
    Integer, String, DateTime, ForeignKey, Boolean, Text, Enum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

MaterialTypeEnum = Enum(
    "document", "video", "link", "presentation", "other",
    name="material_type_enum"
)

class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    link: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    type: Mapped[str] = mapped_column(MaterialTypeEnum, default="document")

    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True, nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True, nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True, nullable=False)

    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subject = relationship("Subject")
    group = relationship("Group")
    teacher = relationship("Teacher")

    @property
    def subject_code(self) -> str | None:
        return self.subject.code if self.subject else None
