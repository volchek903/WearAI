# app/webhooks/platega.py
import os
import hmac
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session  # твой DI/dep
from app.repository.payments import get_payment_by_tx, mark_payment_confirmed
from app.repository.extra import get_plan
from app.repository.payments import apply_plan_to_user  # твоя функция начисления

router = APIRouter()

MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID", "")
SECRET = os.getenv("PLATEGA_SECRET", "")


def safe_eq(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


@router.post("/webhooks/platega")
async def platega_callback(request: Request, session: AsyncSession = get_session()):
    incoming_mid = request.headers.get("X-MerchantId", "")
    incoming_secret = request.headers.get("X-Secret", "")

    if incoming_mid != MERCHANT_ID or not safe_eq(incoming_secret, SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.json()
    tx_id = body.get("id")
    status = body.get("status")

    if not tx_id or not status:
        raise HTTPException(status_code=400, detail="Bad payload")

    payment = await get_payment_by_tx(session, tx_id)
    if not payment:
        return {"ok": True}

    if payment.status == "CONFIRMED":
        return {"ok": True}

    if status == "CONFIRMED":
        plan = await get_plan(session, payment.plan_name)
        if plan:
            await apply_plan_to_user(session, payment.tg_user_id, plan)
        await mark_payment_confirmed(session, payment)

    return {"ok": True}
