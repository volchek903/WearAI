from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user_photo_settings import UserPhotoSettings
    from app.models.admin import Admin
    from app.models.user_subscription import UserSubscription


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_free_generations_day", "free_generations_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    tg_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, index=True, nullable=False
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    credit_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    free_credit_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    free_generations_used_today: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    free_generations_day: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pending_charge_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pending_charge_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pending_charge_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_charge_created_at: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_photos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_videos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    free_channel_bonus_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    free_channel_bonus_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    free_channel_reminder_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    referred_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    referrals_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    photo_settings: Mapped["UserPhotoSettings | None"] = relationship(
        "UserPhotoSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    admin: Mapped["Admin | None"] = relationship(
        "Admin",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    subscriptions: Mapped[list["UserSubscription"]] = relationship(
        "UserSubscription",
        back_populates="user",
        cascade="all, delete-orphan",
    )
