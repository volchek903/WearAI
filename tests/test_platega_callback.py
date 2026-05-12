from __future__ import annotations

import os
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

import app.models  # noqa: F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.payment import Payment, PaymentStatus
from app.models.subscription import Subscription
from app.models.user import User
from app.repository.payments import get_payment_by_id
from app.services.platega_callback import _handle_platega_callback


class _FakeRequest:
    def __init__(self, payload: dict, headers: dict[str, str] | None = None) -> None:
        self._payload = payload
        self.headers = headers or {}

    async def json(self) -> dict:
        return self._payload


class _DummyBot:
    async def send_message(self, *args, **kwargs) -> None:
        del args, kwargs


class _DummyPlategaClient:
    def __init__(self, status: str | None) -> None:
        self._status = status

    async def get_transaction_status(self, tx_id: str) -> str | None:
        del tx_id
        return self._status


class PlategaCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db_path = path
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.db_path}",
            future=True,
        )
        self.sessionmaker = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    async def _seed_confirmed_payment(self) -> Payment:
        async with self.sessionmaker() as session:
            user = User(tg_id=202, username="tester")
            plan = Subscription(
                name="Pulse",
                duration_days=0,
                video_generations=0,
                photo_generations=0,
                credit_amount=220,
                price=Decimal("200.00"),
                stars_price=100,
            )
            payment = Payment(
                tg_user_id=202,
                plan_name="Pulse",
                amount=200,
                currency="RUB",
                credit_amount_snapshot=220,
                platega_transaction_id="tx-confirmed",
                status=PaymentStatus.CONFIRMED,
            )
            session.add_all([user, plan, payment])
            await session.commit()
            await session.refresh(payment)
            return payment

    async def test_canceled_callback_does_not_downgrade_confirmed_payment(self) -> None:
        payment = await self._seed_confirmed_payment()
        request = _FakeRequest(
            {"id": "tx-confirmed", "status": "CANCELED"},
            headers={"X-MerchantId": "merchant", "X-Secret": "secret"},
        )

        with patch.dict(
            os.environ,
            {"PLATEGA_MERCHANT_ID": "merchant", "PLATEGA_SECRET": "secret"},
            clear=False,
        ), patch(
            "app.services.platega_callback.build_platega_client",
            return_value=_DummyPlategaClient("CONFIRMED"),
        ):
            response = await _handle_platega_callback(
                request,
                sessionmaker=self.sessionmaker,
                bot=_DummyBot(),
            )

        self.assertEqual(response.status, 200)

        async with self.sessionmaker() as session:
            stored_payment = await get_payment_by_id(session, payment.id)

        self.assertIsNotNone(stored_payment)
        self.assertEqual(stored_payment.status, PaymentStatus.CONFIRMED)

    async def test_callback_rejects_invalid_secret(self) -> None:
        request = _FakeRequest(
            {"id": "tx-any", "status": "CONFIRMED"},
            headers={"X-MerchantId": "merchant", "X-Secret": "wrong"},
        )

        with patch.dict(
            os.environ,
            {"PLATEGA_MERCHANT_ID": "merchant", "PLATEGA_SECRET": "secret"},
            clear=False,
        ):
            response = await _handle_platega_callback(
                request,
                sessionmaker=self.sessionmaker,
                bot=_DummyBot(),
            )

        self.assertEqual(response.status, 401)

    async def test_callback_uses_provider_status_instead_of_body(self) -> None:
        async with self.sessionmaker() as session:
            user = User(tg_id=303, username="tester")
            plan = Subscription(
                name="Pulse",
                duration_days=0,
                video_generations=0,
                photo_generations=0,
                credit_amount=220,
                price=Decimal("200.00"),
                stars_price=100,
            )
            payment = Payment(
                tg_user_id=303,
                plan_name="Pulse",
                amount=200,
                currency="RUB",
                credit_amount_snapshot=220,
                platega_transaction_id="tx-pending",
                status=PaymentStatus.PENDING,
            )
            session.add_all([user, plan, payment])
            await session.commit()
            await session.refresh(payment)

        request = _FakeRequest(
            {"id": "tx-pending", "status": "CONFIRMED"},
            headers={"X-MerchantId": "merchant", "X-Secret": "secret"},
        )

        with patch.dict(
            os.environ,
            {"PLATEGA_MERCHANT_ID": "merchant", "PLATEGA_SECRET": "secret"},
            clear=False,
        ), patch(
            "app.services.platega_callback.build_platega_client",
            return_value=_DummyPlategaClient("CANCELED"),
        ):
            response = await _handle_platega_callback(
                request,
                sessionmaker=self.sessionmaker,
                bot=_DummyBot(),
            )

        self.assertEqual(response.status, 200)

        async with self.sessionmaker() as session:
            stored_payment = await get_payment_by_id(session, payment.id)
            user = await session.get(User, 1)

        self.assertIsNotNone(stored_payment)
        self.assertEqual(stored_payment.status, PaymentStatus.CANCELED)
        self.assertEqual(int(user.credit_balance), 0)


if __name__ == "__main__":
    unittest.main()
