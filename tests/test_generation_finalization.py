from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import app.models  # noqa: F401
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.repository.users import increment_generated_photos, increment_generated_videos


class GenerationFinalizationTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_user(
        self,
        *,
        tg_id: int,
        pending_charge_kind: str,
        pending_charge_source: str,
        pending_charge_amount: int,
        credit_balance: int = 0,
        free_credit_balance: int = 0,
    ) -> None:
        async with self.sessionmaker() as session:
            user = User(
                tg_id=tg_id,
                username="tester",
                credit_balance=credit_balance,
                free_credit_balance=free_credit_balance,
                pending_charge_kind=pending_charge_kind,
                pending_charge_source=pending_charge_source,
                pending_charge_amount=pending_charge_amount,
                generated_photos=0,
                generated_videos=0,
            )
            session.add(user)
            await session.commit()

    async def test_photo_generation_finalizes_charge_even_if_analytics_fails(self) -> None:
        tg_id = 101
        await self._create_user(
            tg_id=tg_id,
            pending_charge_kind="photo",
            pending_charge_source="paid",
            pending_charge_amount=19,
            credit_balance=81,
        )

        async def _boom(*args, **kwargs):
            raise RuntimeError("analytics failed")

        with patch("app.repository.analytics.log_generation_event", side_effect=_boom):
            async with self.sessionmaker() as session:
                await increment_generated_photos(
                    session=session,
                    tg_id=tg_id,
                    delta=1,
                    section="test_photo",
                )

        async with self.sessionmaker() as session:
            user = await session.get(User, 1)

        assert user is not None
        self.assertEqual(user.pending_charge_kind, None)
        self.assertEqual(user.pending_charge_source, None)
        self.assertEqual(int(user.pending_charge_amount), 0)
        self.assertEqual(int(user.generated_photos), 1)
        self.assertEqual(int(user.credit_balance), 81)

    async def test_video_generation_finalizes_mixed_charge_even_if_analytics_fails(self) -> None:
        tg_id = 202
        await self._create_user(
            tg_id=tg_id,
            pending_charge_kind="video",
            pending_charge_source="mixed:3",
            pending_charge_amount=8,
            credit_balance=12,
            free_credit_balance=4,
        )

        async def _boom(*args, **kwargs):
            raise RuntimeError("analytics failed")

        with patch("app.repository.analytics.log_generation_event", side_effect=_boom):
            async with self.sessionmaker() as session:
                await increment_generated_videos(
                    session=session,
                    tg_id=tg_id,
                    delta=1,
                    section="test_video",
                )

        async with self.sessionmaker() as session:
            user = await session.get(User, 1)

        assert user is not None
        self.assertEqual(user.pending_charge_kind, None)
        self.assertEqual(user.pending_charge_source, None)
        self.assertEqual(int(user.pending_charge_amount), 0)
        self.assertEqual(int(user.generated_videos), 1)
        self.assertEqual(int(user.credit_balance), 12)
        self.assertEqual(int(user.free_credit_balance), 4)


if __name__ == "__main__":
    unittest.main()
