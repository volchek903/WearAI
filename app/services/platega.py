# app/services/platega.py
from __future__ import annotations

import json
import os
import asyncio
import time
from dataclasses import dataclass

import httpx

from app.utils.http_client import external_httpx_client

PAID_STATUSES = {
    "CONFIRMED",
    "PAID",
    "SUCCESS",
    "SUCCEEDED",
    "COMPLETED",
    "APPROVED",
}
CANCELED_STATUSES = {
    "CANCELED",
    "CANCELLED",
    "FAILED",
    "DECLINED",
    "EXPIRED",
    "REJECTED",
}
CHARGEBACK_STATUSES = {"CHARGEBACK", "CHARGEBACKED", "REFUNDED", "REFUND"}


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

        async def _do() -> httpx.Response:
            async with external_httpx_client(timeout=20) as client:
                return await client.post(url, headers=self._headers(), json=body)

        r = await _with_retries(_do)
        r.raise_for_status()
        return r.json()

    async def get_transaction_status(self, tx_id: str) -> str | None:
        url = f"{self.cfg.base_url.rstrip('/')}/transaction/{tx_id}"
        async def _do() -> httpx.Response:
            async with external_httpx_client(timeout=20) as client:
                return await client.get(
                    url,
                    headers={
                        "X-MerchantId": self.cfg.merchant_id,
                        "X-Secret": self.cfg.secret,
                    },
                )

        try:
            r = await _with_retries(_do)
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        data = r.json() or {}
        status = data.get("status")
        if not status and isinstance(data.get("transaction"), dict):
            status = data["transaction"].get("status")
        if not status and isinstance(data.get("data"), dict):
            data_obj = data["data"]
            status = data_obj.get("status")
            if not status and isinstance(data_obj.get("transaction"), dict):
                status = data_obj["transaction"].get("status")
        return str(status) if status else None


async def _with_retries(
    fn, retries: int = 2, backoff_s: float = 1.5
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await fn()
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            last_exc = e
            if attempt >= retries:
                raise
            await asyncio.sleep(backoff_s * (attempt + 1))
        except httpx.HTTPError as e:
            last_exc = e
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("request failed")


def normalize_payment_status(raw_status: str | None) -> str | None:
    if not raw_status:
        return None
    s = str(raw_status).strip().upper()
    if s in PAID_STATUSES:
        return "CONFIRMED"
    if s in CHARGEBACK_STATUSES:
        return "CHARGEBACK"
    if s in CANCELED_STATUSES:
        return "CANCELED"
    return s


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


_HEALTH_TTL_S = 15.0
_last_health_check_ts = 0.0
_last_health_ok = False


async def check_platega_health() -> bool:
    global _last_health_check_ts, _last_health_ok
    now = time.time()
    if now - _last_health_check_ts < _HEALTH_TTL_S:
        return _last_health_ok

    base_url = os.getenv("PLATEGA_BASE_URL") or "https://app.platega.io"
    url = base_url.rstrip("/")
    try:
        async with external_httpx_client(timeout=3) as client:
            r = await client.get(url)
        _last_health_ok = 200 <= r.status_code < 500
    except Exception:
        _last_health_ok = False

    _last_health_check_ts = now
    return _last_health_ok
