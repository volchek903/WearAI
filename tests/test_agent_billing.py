from __future__ import annotations

import os
import tempfile
import unittest

import app.models  # noqa: F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.repository.app_settings import (
    MODEL_PRICE_WEARAI_AGENT_DOCUMENTS_KEY,
    MODEL_PRICE_WEARAI_AGENT_KEY,
    MODEL_PRICE_WEARAI_AGENT_MEMORY_KEY,
    MODEL_PRICE_WEARAI_AGENT_WEB_SEARCH_KEY,
    build_agent_price_breakdown,
    get_agent_request_pricing,
    get_model_price_credits,
    set_agent_daily_free_limit,
)
from app.repository.generations import (
    CHARGE_SOURCE_DAILY_FREE,
    charge_agent_request,
    finalize_agent_request,
    refund_agent_request,
)


class AgentBillingTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_user(self, *, tg_id: int, credit_balance: int = 0) -> None:
        async with self.sessionmaker() as session:
            session.add(
                User(
                    tg_id=tg_id,
                    username="tester",
                    credit_balance=credit_balance,
                    free_credit_balance=0,
                    free_generations_used_today=0,
                    free_generations_day=None,
                    free_agent_requests_used_today=0,
                    free_agent_requests_day=None,
                    pending_charge_kind=None,
                    pending_charge_source=None,
                    pending_charge_amount=0,
                    pending_charge_created_at=0,
                    generated_photos=0,
                    generated_videos=0,
                )
            )
            await session.commit()

    async def test_default_agent_base_and_addons_match_expected_values(self) -> None:
        async with self.sessionmaker() as session:
            base_price = await get_model_price_credits(session, MODEL_PRICE_WEARAI_AGENT_KEY)
            memory_price = await get_model_price_credits(
                session,
                MODEL_PRICE_WEARAI_AGENT_MEMORY_KEY,
            )
            documents_price = await get_model_price_credits(
                session,
                MODEL_PRICE_WEARAI_AGENT_DOCUMENTS_KEY,
            )
            web_price = await get_model_price_credits(
                session,
                MODEL_PRICE_WEARAI_AGENT_WEB_SEARCH_KEY,
            )

        self.assertEqual(base_price, 5)
        self.assertEqual(memory_price, 2)
        self.assertEqual(documents_price, 2)
        self.assertEqual(web_price, 1)

    async def test_agent_price_breakdown_sums_base_and_addons(self) -> None:
        async with self.sessionmaker() as session:
            pricing = await get_agent_request_pricing(session)

        breakdown = build_agent_price_breakdown(
            pricing,
            memory_enabled=True,
            documents_enabled=True,
            web_search_enabled=True,
            deep_analysis_enabled=False,
            quick_mode_enabled=False,
        )

        self.assertEqual(breakdown.base, 5)
        self.assertEqual(breakdown.total, 10)

    async def test_first_agent_request_uses_daily_free_limit(self) -> None:
        tg_id = 9001
        await self._create_user(tg_id=tg_id, credit_balance=20)

        async with self.sessionmaker() as session:
            await set_agent_daily_free_limit(session, 1)
            result = await charge_agent_request(session, tg_id=tg_id, credits_override=5)
            await finalize_agent_request(session, tg_id)

        self.assertEqual(result.source, CHARGE_SOURCE_DAILY_FREE)
        self.assertEqual(result.amount, 0)

        async with self.sessionmaker() as session:
            user = await session.get(User, 1)

        assert user is not None
        self.assertEqual(int(user.credit_balance), 20)
        self.assertEqual(int(user.free_agent_requests_used_today), 1)
        self.assertIsNotNone(user.free_agent_requests_day)
        self.assertEqual(user.pending_charge_kind, None)
        self.assertEqual(user.pending_charge_source, None)
        self.assertEqual(int(user.pending_charge_amount), 0)

    async def test_refund_agent_daily_free_request_restores_slot(self) -> None:
        tg_id = 9002
        await self._create_user(tg_id=tg_id, credit_balance=20)

        async with self.sessionmaker() as session:
            await set_agent_daily_free_limit(session, 1)
            await charge_agent_request(session, tg_id=tg_id, credits_override=5)
            await refund_agent_request(session, tg_id)

        async with self.sessionmaker() as session:
            user = await session.get(User, 1)

        assert user is not None
        self.assertEqual(int(user.credit_balance), 20)
        self.assertEqual(int(user.free_agent_requests_used_today), 0)
        self.assertEqual(user.pending_charge_kind, None)
        self.assertEqual(user.pending_charge_source, None)
        self.assertEqual(int(user.pending_charge_amount), 0)

    async def test_agent_request_charges_credits_after_free_limit_is_exhausted(self) -> None:
        tg_id = 9003
        await self._create_user(tg_id=tg_id, credit_balance=20)

        async with self.sessionmaker() as session:
            await set_agent_daily_free_limit(session, 1)
            await charge_agent_request(session, tg_id=tg_id, credits_override=5)
            await finalize_agent_request(session, tg_id)
            result = await charge_agent_request(session, tg_id=tg_id, credits_override=5)
            await finalize_agent_request(session, tg_id)

        self.assertEqual(result.source, "paid")
        self.assertEqual(result.amount, 5)

        async with self.sessionmaker() as session:
            user = await session.get(User, 1)

        assert user is not None
        self.assertEqual(int(user.credit_balance), 15)
        self.assertEqual(int(user.free_agent_requests_used_today), 1)
        self.assertEqual(user.pending_charge_kind, None)
        self.assertEqual(user.pending_charge_source, None)
        self.assertEqual(int(user.pending_charge_amount), 0)

    async def test_agent_request_prefers_paid_when_expensive_modes_are_enabled(self) -> None:
        tg_id = 9004
        await self._create_user(tg_id=tg_id, credit_balance=20)

        async with self.sessionmaker() as session:
            await set_agent_daily_free_limit(session, 1)
            result = await charge_agent_request(
                session,
                tg_id=tg_id,
                credits_override=9,
                prefer_paid=True,
            )
            await finalize_agent_request(session, tg_id)

        self.assertEqual(result.source, "paid")
        self.assertEqual(result.amount, 9)

        async with self.sessionmaker() as session:
            user = await session.get(User, 1)

        assert user is not None
        self.assertEqual(int(user.credit_balance), 11)
        self.assertEqual(int(user.free_agent_requests_used_today), 0)

    async def test_agent_request_falls_back_to_free_when_no_balance_for_paid_mode(self) -> None:
        tg_id = 9005
        await self._create_user(tg_id=tg_id, credit_balance=0)

        async with self.sessionmaker() as session:
            await set_agent_daily_free_limit(session, 1)
            result = await charge_agent_request(
                session,
                tg_id=tg_id,
                credits_override=5,
                prefer_paid=True,
            )
            await finalize_agent_request(session, tg_id)

        self.assertEqual(result.source, CHARGE_SOURCE_DAILY_FREE)
        self.assertEqual(result.amount, 0)


if __name__ == "__main__":
    unittest.main()
