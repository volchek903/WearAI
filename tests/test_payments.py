from __future__ import annotations

import os
import tempfile
import unittest
from decimal import Decimal

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.payment import Payment, PaymentStatus
from app.models.subscription import Subscription
from app.models.user import User
from app.repository.payments import (
    PaymentAlreadyProcessedError,
    PaymentPlanNotFoundError,
    confirm_payment_and_apply_credits,
    get_payment_by_id,
)


class PaymentConfirmationTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_user(self, *, tg_id: int = 101) -> User:
        async with self.sessionmaker() as session:
            user = User(tg_id=tg_id, username="tester")
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def _create_plan(self, *, name: str = "Pulse", credits: int = 220) -> Subscription:
        async with self.sessionmaker() as session:
            plan = Subscription(
                name=name,
                duration_days=0,
                video_generations=0,
                photo_generations=0,
                credit_amount=credits,
                price=Decimal("200.00"),
                stars_price=100,
            )
            session.add(plan)
            await session.commit()
            await session.refresh(plan)
            return plan

    async def _create_payment(self, *, tg_id: int = 101, plan_name: str = "Pulse") -> Payment:
        async with self.sessionmaker() as session:
            payment = Payment(
                tg_user_id=tg_id,
                plan_name=plan_name,
                amount=200,
                currency="RUB",
                platega_transaction_id=f"tx-{tg_id}-{plan_name}",
                status=PaymentStatus.PENDING,
            )
            session.add(payment)
            await session.commit()
            await session.refresh(payment)
            return payment

    async def test_confirm_payment_applies_credits_and_marks_confirmed(self) -> None:
        await self._create_user()
        await self._create_plan()
        payment = await self._create_payment()

        async with self.sessionmaker() as session:
            db_payment = await get_payment_by_id(session, payment.id)
            assert db_payment is not None
            credited = await confirm_payment_and_apply_credits(session, db_payment)

        self.assertEqual(credited, 220)

        async with self.sessionmaker() as session:
            stored_payment = await get_payment_by_id(session, payment.id)
            user = await session.get(User, 1)

        self.assertIsNotNone(stored_payment)
        self.assertEqual(stored_payment.status, PaymentStatus.CONFIRMED)
        self.assertEqual(int(user.credit_balance), 220)

    async def test_confirm_payment_with_missing_plan_keeps_payment_pending(self) -> None:
        await self._create_user()
        payment = await self._create_payment(plan_name="MissingPlan")

        async with self.sessionmaker() as session:
            db_payment = await get_payment_by_id(session, payment.id)
            assert db_payment is not None
            with self.assertRaises(PaymentPlanNotFoundError):
                await confirm_payment_and_apply_credits(session, db_payment)

        async with self.sessionmaker() as session:
            stored_payment = await get_payment_by_id(session, payment.id)
            user = await session.get(User, 1)

        self.assertIsNotNone(stored_payment)
        self.assertEqual(stored_payment.status, PaymentStatus.PENDING)
        self.assertEqual(int(user.credit_balance), 0)

    async def test_confirm_payment_rejects_stale_second_attempt(self) -> None:
        await self._create_user()
        await self._create_plan()
        payment = await self._create_payment()

        async with self.sessionmaker() as session1, self.sessionmaker() as session2:
            payment1 = await get_payment_by_id(session1, payment.id)
            payment2 = await get_payment_by_id(session2, payment.id)
            assert payment1 is not None
            assert payment2 is not None

            credited = await confirm_payment_and_apply_credits(session1, payment1)
            self.assertEqual(credited, 220)

            with self.assertRaises(PaymentAlreadyProcessedError):
                await confirm_payment_and_apply_credits(session2, payment2)

        async with self.sessionmaker() as session:
            stored_payment = await get_payment_by_id(session, payment.id)
            user = await session.get(User, 1)

        self.assertIsNotNone(stored_payment)
        self.assertEqual(stored_payment.status, PaymentStatus.CONFIRMED)
        self.assertEqual(int(user.credit_balance), 220)


if __name__ == "__main__":
    unittest.main()
