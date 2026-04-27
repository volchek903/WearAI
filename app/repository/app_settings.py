from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_UP

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting


MODEL_PRICE_NANO_BANANA_KEY = "model_price_nano_banana_2_photo"
MODEL_PRICE_NANO_BANANA_PRO_KEY = "model_price_nano_banana_pro_photo"
MODEL_PRICE_SEEDREAM_V5_LITE_KEY = "model_price_seedream_v5_lite_photo"
MODEL_PRICE_SEEDREAM_V45_KEY = "model_price_seedream_v45_text_to_image"
MODEL_PRICE_WAN_27_KEY = "model_price_wan_27_text_to_image"
MODEL_PRICE_GPT_IMAGE_2_EDIT_KEY = "model_price_gpt_image_2_edit"
MODEL_PRICE_GPT_IMAGE_2_TEXT_TO_IMAGE_KEY = "model_price_gpt_image_2_text_to_image"
MODEL_PRICE_KLING_I2V_KEY = "model_price_kling_v30_std_i2v"
MODEL_PRICE_KLING_MOTION_KEY = "model_price_kling_v26_std_motion"
MODEL_PRICE_ACE_STEP_KEY = "model_price_ace_step_1_5_music_per_second"
PRICING_MARKUP_MULTIPLIER_KEY = "pricing_markup_multiplier_pct"
USD_TO_RUB_RATE_KEY = "pricing_usd_to_rub_rate"

DEFAULT_USD_TO_RUB_RATE = 79
DEFAULT_MARKUP_MULTIPLIER_PCT = 300

# WaveSpeed public pricing snapshot used to seed defaults.
DEFAULT_PROVIDER_COST_USD = {
    MODEL_PRICE_NANO_BANANA_KEY: Decimal("0.08"),
    MODEL_PRICE_NANO_BANANA_PRO_KEY: Decimal("0.14"),
    MODEL_PRICE_SEEDREAM_V5_LITE_KEY: Decimal("0.035"),
    MODEL_PRICE_SEEDREAM_V45_KEY: Decimal("0.04"),
    MODEL_PRICE_WAN_27_KEY: Decimal("0.03"),
    MODEL_PRICE_GPT_IMAGE_2_EDIT_KEY: Decimal("0.06"),
    MODEL_PRICE_GPT_IMAGE_2_TEXT_TO_IMAGE_KEY: Decimal("0.06"),
    MODEL_PRICE_KLING_I2V_KEY: Decimal("0.42"),
    MODEL_PRICE_KLING_MOTION_KEY: Decimal("0.21"),
    MODEL_PRICE_ACE_STEP_KEY: Decimal("0.0003"),
}


@dataclass(frozen=True, slots=True)
class ModelPricing:
    model_key: str
    title: str
    provider_cost_usd: Decimal
    user_price_credits: int


MODEL_TITLES = {
    MODEL_PRICE_NANO_BANANA_KEY: "Фото: Nano Banana 2",
    MODEL_PRICE_NANO_BANANA_PRO_KEY: "Фото: Nano Banana Pro",
    MODEL_PRICE_SEEDREAM_V5_LITE_KEY: "Фото: Seedream 5 Lite",
    MODEL_PRICE_SEEDREAM_V45_KEY: "Фото: Seedream 4.5",
    MODEL_PRICE_WAN_27_KEY: "Фото: Wan 2.7",
    MODEL_PRICE_GPT_IMAGE_2_EDIT_KEY: "Фото: GPT Image 2 Edit (base 1K medium)",
    MODEL_PRICE_GPT_IMAGE_2_TEXT_TO_IMAGE_KEY: "Фото: GPT Image 2 Text-to-Image (base 1K medium)",
    MODEL_PRICE_KLING_I2V_KEY: "Видео: Kling 3.0 Std I2V",
    MODEL_PRICE_KLING_MOTION_KEY: "Видео: Kling 2.6 Std Motion",
    MODEL_PRICE_ACE_STEP_KEY: "Музыка: ACE-Step 1.5 (за 1 сек.)",
}

LAUNCH_DAILY_LIMIT_KEY = "launch_daily_limit"


async def _get_int_setting(session: AsyncSession, key: str, default: int) -> int:
    val = await session.scalar(
        select(AppSetting.int_value).where(AppSetting.key == key)
    )
    if val is None:
        session.add(AppSetting(key=key, int_value=int(default)))
        await session.commit()
        return int(default)
    return int(val)


async def _set_int_setting(session: AsyncSession, key: str, value: int) -> None:
    updated = await session.execute(
        update(AppSetting)
        .where(AppSetting.key == key)
        .values(int_value=int(value))
    )
    if updated.rowcount == 0:
        session.add(AppSetting(key=key, int_value=int(value)))
    await session.commit()


def _credits_from_provider_cost(
    provider_cost_usd: Decimal,
    *,
    usd_to_rub_rate: int,
    markup_multiplier_pct: int,
) -> int:
    rub = provider_cost_usd * Decimal(int(usd_to_rub_rate))
    multiplier = Decimal(int(markup_multiplier_pct)) / Decimal("100")
    return max(1, int((rub * multiplier).quantize(Decimal("1"), rounding=ROUND_UP)))


async def ensure_model_pricing_settings(session: AsyncSession) -> None:
    usd_to_rub_rate = await _get_int_setting(
        session,
        USD_TO_RUB_RATE_KEY,
        DEFAULT_USD_TO_RUB_RATE,
    )
    markup_multiplier_pct = await _get_int_setting(
        session,
        PRICING_MARKUP_MULTIPLIER_KEY,
        DEFAULT_MARKUP_MULTIPLIER_PCT,
    )

    for key, provider_cost_usd in DEFAULT_PROVIDER_COST_USD.items():
        default_price = _credits_from_provider_cost(
            provider_cost_usd,
            usd_to_rub_rate=usd_to_rub_rate,
            markup_multiplier_pct=markup_multiplier_pct,
        )
        await _get_int_setting(session, key, default_price)


async def get_launch_daily_limit(session: AsyncSession) -> int:
    return await _get_int_setting(session, LAUNCH_DAILY_LIMIT_KEY, 0)


async def set_launch_daily_limit(session: AsyncSession, value: int) -> None:
    await _set_int_setting(session, LAUNCH_DAILY_LIMIT_KEY, int(value))


async def get_pricing_markup_multiplier_pct(session: AsyncSession) -> int:
    return await _get_int_setting(
        session, PRICING_MARKUP_MULTIPLIER_KEY, DEFAULT_MARKUP_MULTIPLIER_PCT
    )


async def set_pricing_markup_multiplier_pct(session: AsyncSession, value: int) -> None:
    await _set_int_setting(session, PRICING_MARKUP_MULTIPLIER_KEY, max(100, int(value)))


async def get_usd_to_rub_rate(session: AsyncSession) -> int:
    return await _get_int_setting(session, USD_TO_RUB_RATE_KEY, DEFAULT_USD_TO_RUB_RATE)


async def set_usd_to_rub_rate(session: AsyncSession, value: int) -> None:
    await _set_int_setting(session, USD_TO_RUB_RATE_KEY, max(1, int(value)))


async def get_model_price_credits(session: AsyncSession, model_key: str) -> int:
    if model_key not in MODEL_TITLES:
        raise KeyError(f"Unknown pricing model key: {model_key}")
    await ensure_model_pricing_settings(session)
    return await _get_int_setting(session, model_key, 0)


async def get_scaled_model_price_credits(
    session: AsyncSession,
    model_key: str,
    provider_cost_usd: Decimal,
) -> int:
    if model_key not in DEFAULT_PROVIDER_COST_USD:
        raise KeyError(f"Unknown pricing model key: {model_key}")

    base_cost = DEFAULT_PROVIDER_COST_USD[model_key]
    if base_cost <= 0 or provider_cost_usd <= 0:
        return await get_model_price_credits(session, model_key)

    base_price = await get_model_price_credits(session, model_key)
    scaled_price = (
        Decimal(base_price) * (provider_cost_usd / base_cost)
    ).quantize(Decimal("1"), rounding=ROUND_UP)
    return max(1, int(scaled_price))


async def set_model_price_credits(
    session: AsyncSession, model_key: str, value: int
) -> None:
    if model_key not in MODEL_TITLES:
        raise KeyError(f"Unknown pricing model key: {model_key}")
    await _set_int_setting(session, model_key, max(1, int(value)))


async def list_model_pricing(session: AsyncSession) -> list[ModelPricing]:
    await ensure_model_pricing_settings(session)
    items: list[ModelPricing] = []
    for key, title in MODEL_TITLES.items():
        items.append(
            ModelPricing(
                model_key=key,
                title=title,
                provider_cost_usd=DEFAULT_PROVIDER_COST_USD[key],
                user_price_credits=await get_model_price_credits(session, key),
            )
        )
    return items


async def reset_model_pricing_from_costs(session: AsyncSession) -> None:
    usd_to_rub_rate = await get_usd_to_rub_rate(session)
    markup_multiplier_pct = await get_pricing_markup_multiplier_pct(session)
    for key, provider_cost_usd in DEFAULT_PROVIDER_COST_USD.items():
        value = _credits_from_provider_cost(
            provider_cost_usd,
            usd_to_rub_rate=usd_to_rub_rate,
            markup_multiplier_pct=markup_multiplier_pct,
        )
        await _set_int_setting(session, key, value)
