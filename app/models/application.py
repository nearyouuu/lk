from datetime import datetime
from sqlalchemy import (
    Integer, String, Text, DateTime, Enum, ForeignKey
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

ApplicationTypeEnum = Enum(
    "certificate",
    "statement",
    "academic",
    "other",
    name="application_type_enum"
)

ApplicationStatusEnum = Enum(
    "new",
    "in_progress",
    "approved",
    "rejected",
    name="application_status_enum"
)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(ApplicationTypeEnum, default="certificate")
    title: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(ApplicationStatusEnum, default="new")
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    student = relationship("Student", back_populates="applications")
