from datetime import datetime
from sqlalchemy import (
    Integer, String, Boolean, DateTime, ForeignKey, Text, func, Table, Column
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

news_tags_table = Table(
    "news_tags_link",
    Base.metadata,
    Column("news_id", ForeignKey("news.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("news_tags.id", ondelete="CASCADE"), primary_key=True),
)

class Tag(Base):
    __tablename__ = "news_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    author = relationship("User")

    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    photo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    tags = relationship("Tag", secondary=news_tags_table, backref="news_list", lazy="joined")
