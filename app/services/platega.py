# app/services/platega.py
from __future__ import annotations

import json
import os
import asyncio
import time
import logging
from dataclasses import dataclass

import httpx

from app.utils.http_client import external_httpx_client

logger = logging.getLogger(__name__)

PLATEGA_PAYMENT_METHOD_IDS = {
    "sbp": 2,
    "card": 11,
    "crypto": 13,
}
DEFAULT_PLATEGA_ENABLED_METHODS = ("sbp",)

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
    api_version: str = "v1"
    v2_send_payment_method: bool = False


class PlategaClient:
    def __init__(self, cfg: PlategaConfig) -> None:
        self.cfg = cfg

    @property
    def _root_url(self) -> str:
        return _platega_root_url(self.cfg.base_url)

    def _transaction_process_url(self, api_version: str | None = None) -> str:
        version = _normalize_platega_api_version(api_version or self.cfg.api_version)
        if version == "v2":
            return f"{self._root_url}/v2/transaction/process"
        return f"{self._root_url}/transaction/process"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-MerchantId": self.cfg.merchant_id,
            "X-Secret": self.cfg.secret,
        }

    def _payment_body(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        payload: dict,
        payment_method: int,
        api_version: str,
    ) -> dict:
        body = {
            "paymentDetails": {"amount": amount, "currency": currency},
            "description": description,
            "return": self.cfg.return_url,
            "failedUrl": self.cfg.failed_url,
            "payload": json.dumps(payload, ensure_ascii=False),
        }
        if (
            _normalize_platega_api_version(api_version) == "v1"
            or self.cfg.v2_send_payment_method
        ):
            body["paymentMethod"] = payment_method
        return body

    async def create_payment_link(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        payload: dict,
        payment_method: int = 2,
    ) -> dict:
        api_version = _normalize_platega_api_version(self.cfg.api_version)

        async def _post(url: str, body: dict) -> httpx.Response:
            async with external_httpx_client(timeout=20) as client:
                return await client.post(url, headers=self._headers(), json=body)

        body = self._payment_body(
            amount=amount,
            currency=currency,
            description=description,
            payload=payload,
            payment_method=payment_method,
            api_version=api_version,
        )
        url = self._transaction_process_url(api_version)
        r = await _with_retries(lambda: _post(url, body))
        if r.status_code >= 400:
            self._log_create_failure(r, payment_method, amount, currency, url)
            if (
                api_version == "v1"
                and payment_method != PLATEGA_PAYMENT_METHOD_IDS["sbp"]
            ):
                fallback_url = self._transaction_process_url("v2")
                fallback_body = self._payment_body(
                    amount=amount,
                    currency=currency,
                    description=description,
                    payload=payload,
                    payment_method=payment_method,
                    api_version="v2",
                )
                logger.warning(
                    "platega.create_payment_link: retrying via v2 endpoint payment_method=%s amount=%s currency=%s",
                    payment_method,
                    amount,
                    currency,
                )
                r = await _with_retries(lambda: _post(fallback_url, fallback_body))
                if r.status_code >= 400:
                    self._log_create_failure(
                        r, payment_method, amount, currency, fallback_url
                    )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "redirect" not in data and data.get("url"):
            data["redirect"] = data["url"]
        return data

    def _log_create_failure(
        self,
        response: httpx.Response,
        payment_method: int,
        amount: int,
        currency: str,
        url: str,
    ) -> None:
        logger.warning(
            "platega.create_payment_link: non-success status=%s url=%s payment_method=%s amount=%s currency=%s response=%s",
            response.status_code,
            url,
            payment_method,
            amount,
            currency,
            (response.text or "")[:1000],
        )

    async def get_transaction_status(self, tx_id: str) -> str | None:
        url = f"{self._root_url}/transaction/{tx_id}"

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


def _platega_root_url(base_url: str) -> str:
    url = (base_url or "https://app.platega.io").strip().rstrip("/")
    if not url:
        url = "https://app.platega.io"
    prefix, _, suffix = url.rpartition("/")
    if prefix and suffix.lower() in {"v1", "v2"}:
        return prefix
    return url


def _normalize_platega_api_version(raw: str | None) -> str:
    version = (raw or "v1").strip().lower().lstrip("/")
    if version in {"2", "v2"}:
        return "v2"
    return "v1"


def _default_platega_api_version(base_url: str) -> str:
    configured = os.getenv("PLATEGA_API_VERSION")
    if configured:
        return configured
    suffix = (base_url or "").strip().rstrip("/").rpartition("/")[2].lower()
    if suffix in {"v1", "v2"}:
        return suffix
    return "v1"


def _env_truthy(name: str, default: str = "0") -> bool:
    return (os.getenv(name) or default).strip().lower() in {"1", "true", "yes", "on"}


def build_platega_client() -> PlategaClient:
    base_url = os.getenv("PLATEGA_BASE_URL") or "https://app.platega.io"
    cfg = PlategaConfig(
        base_url=base_url,
        merchant_id=os.getenv("PLATEGA_MERCHANT_ID") or "",
        secret=os.getenv("PLATEGA_SECRET") or "",
        return_url=os.getenv("PLATEGA_RETURN_URL") or "",
        failed_url=os.getenv("PLATEGA_FAILED_URL") or "",
        api_version=_default_platega_api_version(base_url),
        v2_send_payment_method=_env_truthy("PLATEGA_V2_SEND_PAYMENT_METHOD"),
    )
    if not cfg.merchant_id or not cfg.secret:
        raise RuntimeError("PLATEGA_MERCHANT_ID / PLATEGA_SECRET are required")
    # return_url/failed_url можно оставить пустыми, если тебе не важен редирект
    return PlategaClient(cfg)


def enabled_platega_methods() -> tuple[str, ...]:
    raw = os.getenv("PLATEGA_ENABLED_METHODS")
    if raw is None:
        return DEFAULT_PLATEGA_ENABLED_METHODS

    methods: list[str] = []
    for item in raw.split(","):
        method = item.strip().lower()
        if method in PLATEGA_PAYMENT_METHOD_IDS and method not in methods:
            methods.append(method)
    return tuple(methods)


def resolve_platega_payment_method(method: str) -> int | None:
    normalized = (method or "").strip().lower()
    if normalized not in enabled_platega_methods():
        return None
    return PLATEGA_PAYMENT_METHOD_IDS.get(normalized)


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
