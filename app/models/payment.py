# app/models/payment.py
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELED = "CANCELED"
    CHARGEBACK = "CHARGEBACK"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # В PYTHON: tg_user_id
    # В БД КОЛОНКА: user_tg_id (без миграции)
    tg_user_id: Mapped[int] = mapped_column(
        "user_tg_id", BigInteger, nullable=False, index=True
    )

    plan_name: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")

    platega_transaction_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
