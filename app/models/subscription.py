from __future__ import annotations

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Subscription(Base):
    __tablename__ = "subscription"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Например: "Launch", "Orbit", "Nova", "Cosmic"
    name: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_generations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    photo_generations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
