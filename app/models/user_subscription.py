from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, SmallInteger, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserSubscription(Base):
    __tablename__ = "user_subscription"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscription.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    remaining_video: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remaining_photo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 1 = active, 0 = inactive
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, index=True
    )

    subscription = relationship("Subscription")
