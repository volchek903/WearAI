from __future__ import annotations

from sqlalchemy import text

from app.db.session import engine
from app.models.base import Base


async def _ensure_sqlite_columns() -> None:
    if engine.url.get_backend_name() != "sqlite":
        return
    async with engine.begin() as conn:
        user_cols = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA table_info(users)"))
            ).fetchall()
        }
        if "credit_balance" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN credit_balance INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "free_credit_balance" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN free_credit_balance INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "free_generations_used_today" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN free_generations_used_today INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "free_generations_day" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN free_generations_day VARCHAR(10)"
                )
            )
        if "free_agent_requests_used_today" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN free_agent_requests_used_today INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "free_agent_requests_day" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN free_agent_requests_day VARCHAR(10)"
                )
            )
        if "pending_charge_kind" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN pending_charge_kind VARCHAR(16)"
                )
            )
        if "pending_charge_source" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN pending_charge_source VARCHAR(16)"
                )
            )
        if "pending_charge_amount" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN pending_charge_amount INTEGER NOT NULL DEFAULT 0"
                )
            )
        if "pending_charge_created_at" not in user_cols:
            await conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN pending_charge_created_at INTEGER NOT NULL DEFAULT 0"
                )
            )

        promo_cols = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA table_info(promo_codes)"))
            ).fetchall()
        }
        if "bonus_credits" not in promo_cols:
            await conn.execute(
                text(
                    "ALTER TABLE promo_codes ADD COLUMN bonus_credits INTEGER NOT NULL DEFAULT 0"
                )
            )

        sub_cols = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA table_info(subscription)"))
            ).fetchall()
        }
        if "credit_amount" not in sub_cols:
            await conn.execute(
                text(
                    "ALTER TABLE subscription ADD COLUMN credit_amount INTEGER NOT NULL DEFAULT 0"
                )
            )

        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_users_free_generations_day "
                "ON users(free_generations_day)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_users_free_agent_requests_day "
                "ON users(free_agent_requests_day)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_payments_user_tg_status_id "
                "ON payments(user_tg_id, status, id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_payments_status_id "
                "ON payments(status, id)"
            )
        )

        payment_cols = {
            row[1]
            for row in (
                await conn.execute(text("PRAGMA table_info(payments)"))
            ).fetchall()
        }
        if "credit_amount_snapshot" not in payment_cols:
            await conn.execute(
                text(
                    "ALTER TABLE payments ADD COLUMN credit_amount_snapshot INTEGER NOT NULL DEFAULT 0"
                )
            )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_sqlite_columns()
