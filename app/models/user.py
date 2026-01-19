from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user_photo_settings import UserPhotoSettings
    from app.models.admin import Admin


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    tg_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # roles: "admin" / "user"
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")

    # subscription
    subscription_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    subscription_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # limits / counters
    generations_left: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_photos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # 1:1 настройки генерации фото
    photo_settings: Mapped["UserPhotoSettings | None"] = relationship(
        "UserPhotoSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    # 1:1 признак администратора через таблицу admin
    admin: Mapped["Admin | None"] = relationship(
        "Admin",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
