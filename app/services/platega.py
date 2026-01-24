# app/services/platega.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx


@dataclass
class PlategaConfig:
    base_url: str
    merchant_id: str
    secret: str
    return_url: str
    failed_url: str


class PlategaClient:
    def __init__(self, cfg: PlategaConfig) -> None:
        self.cfg = cfg

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-MerchantId": self.cfg.merchant_id,
            "X-Secret": self.cfg.secret,
        }

    async def create_payment_link(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        payload: dict,
        payment_method: int = 2,
    ) -> dict:
        url = f"{self.cfg.base_url.rstrip('/')}/transaction/process"
        body = {
            "paymentMethod": payment_method,
            "paymentDetails": {"amount": amount, "currency": currency},
            "description": description,
            "return": self.cfg.return_url,
            "failedUrl": self.cfg.failed_url,
            "payload": json.dumps(payload, ensure_ascii=False),
        }

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json()

    async def get_transaction_status(self, tx_id: str) -> str | None:
        url = f"{self.cfg.base_url.rstrip('/')}/transaction/{tx_id}"
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                url,
                headers={
                    "X-MerchantId": self.cfg.merchant_id,
                    "X-Secret": self.cfg.secret,
                },
            )
        if r.status_code != 200:
            return None
        return (r.json() or {}).get("status")


def build_platega_client() -> PlategaClient:
    cfg = PlategaConfig(
        base_url=os.getenv("PLATEGA_BASE_URL") or "https://app.platega.io",
        merchant_id=os.getenv("PLATEGA_MERCHANT_ID") or "",
        secret=os.getenv("PLATEGA_SECRET") or "",
        return_url=os.getenv("PLATEGA_RETURN_URL") or "",
        failed_url=os.getenv("PLATEGA_FAILED_URL") or "",
    )
    if not cfg.merchant_id or not cfg.secret:
        raise RuntimeError("PLATEGA_MERCHANT_ID / PLATEGA_SECRET are required")
    # return_url/failed_url можно оставить пустыми, если тебе не важен редирект
    return PlategaClient(cfg)
