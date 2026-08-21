from datetime import date, datetime
from sqlalchemy import String, Boolean, Date, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    students = relationship(
        "Student",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    admin_profile = relationship(
        "AdminProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False
    )

    director_profile = relationship(
        "Director",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False
    )

    roles = relationship("Role", secondary="user_roles", back_populates="users")
