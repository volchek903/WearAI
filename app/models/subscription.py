from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user_subscription import UserSubscription


class Subscription(Base):
    __tablename__ = "subscription"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_generations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    photo_generations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)

    user_subscriptions: Mapped[list["UserSubscription"]] = relationship(
        "UserSubscription",
        back_populates="subscription",
        cascade="all, delete-orphan",
    )
