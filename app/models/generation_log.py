from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class GenerationLog(Base):
    __tablename__ = "generation_log"

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

    user_subscription_id: Mapped[int] = mapped_column(
        ForeignKey("user_subscription.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # "photo" | "video"
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    user = relationship("User")
    subscription = relationship("Subscription")
    user_subscription = relationship("UserSubscription")
