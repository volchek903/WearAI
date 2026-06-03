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
MODEL_PRICE_SEEDANCE_20_VIDEO_PER_SECOND_KEY = "model_price_seedance_20_video_per_second"
MODEL_PRICE_SEEDANCE_20_TURBO_VIDEO_PER_SECOND_KEY = "model_price_seedance_20_turbo_video_per_second"
MODEL_PRICE_HAPPY_HORSE_10_VIDEO_PER_SECOND_KEY = "model_price_happy_horse_10_video_per_second"
MODEL_PRICE_WAN_27_VIDEO_PER_SECOND_KEY = "model_price_wan_27_video_per_second"
MODEL_PRICE_WAN_22_SPICY_VIDEO_PER_SECOND_KEY = "model_price_wan_22_spicy_video_per_second"
MODEL_PRICE_KLING_30_VIDEO_PER_SECOND_KEY = "model_price_kling_30_video_per_second"
MODEL_PRICE_KLING_O3_VIDEO_PER_SECOND_KEY = "model_price_kling_o3_video_per_second"
MODEL_PRICE_VEO_31_LITE_VIDEO_PER_SECOND_KEY = "model_price_veo_31_lite_video_per_second"
MODEL_PRICE_GROK_IMAGINE_VIDEO_PER_SECOND_KEY = "model_price_grok_imagine_video_per_second"
MODEL_PRICE_WEARAI_AGENT_KEY = "model_price_wearai_agent_request"
MODEL_PRICE_WEARAI_AGENT_MEMORY_KEY = "model_price_wearai_agent_memory_addon"
MODEL_PRICE_WEARAI_AGENT_DOCUMENTS_KEY = "model_price_wearai_agent_documents_addon"
MODEL_PRICE_WEARAI_AGENT_WEB_SEARCH_KEY = "model_price_wearai_agent_web_search_addon"
MODEL_PRICE_WEARAI_AGENT_DEEP_ANALYSIS_KEY = "model_price_wearai_agent_deep_analysis_addon"
MODEL_PRICE_WEARAI_AGENT_QUICK_MODE_KEY = "model_price_wearai_agent_quick_mode_addon"
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
    MODEL_PRICE_SEEDANCE_20_VIDEO_PER_SECOND_KEY: Decimal("0.12"),
    MODEL_PRICE_SEEDANCE_20_TURBO_VIDEO_PER_SECOND_KEY: Decimal("0.14"),
    MODEL_PRICE_HAPPY_HORSE_10_VIDEO_PER_SECOND_KEY: Decimal("0.14"),
    MODEL_PRICE_WAN_27_VIDEO_PER_SECOND_KEY: Decimal("0.10"),
    MODEL_PRICE_WAN_22_SPICY_VIDEO_PER_SECOND_KEY: Decimal("0.03"),
    MODEL_PRICE_KLING_30_VIDEO_PER_SECOND_KEY: Decimal("0.084"),
    MODEL_PRICE_KLING_O3_VIDEO_PER_SECOND_KEY: Decimal("0.084"),
    MODEL_PRICE_VEO_31_LITE_VIDEO_PER_SECOND_KEY: Decimal("0.05"),
    MODEL_PRICE_GROK_IMAGINE_VIDEO_PER_SECOND_KEY: Decimal("0.05"),
    MODEL_PRICE_WEARAI_AGENT_KEY: Decimal("0.02"),
    MODEL_PRICE_WEARAI_AGENT_MEMORY_KEY: Decimal("0.008"),
    MODEL_PRICE_WEARAI_AGENT_DOCUMENTS_KEY: Decimal("0.008"),
    MODEL_PRICE_WEARAI_AGENT_WEB_SEARCH_KEY: Decimal("0.003"),
    MODEL_PRICE_WEARAI_AGENT_DEEP_ANALYSIS_KEY: Decimal("0.002"),
    MODEL_PRICE_WEARAI_AGENT_QUICK_MODE_KEY: Decimal("0.001"),
}


@dataclass(frozen=True, slots=True)
class ModelPricing:
    model_key: str
    title: str
    provider_cost_usd: Decimal
    user_price_credits: int


@dataclass(frozen=True, slots=True)
class AgentRequestPricing:
    base: int
    memory: int
    documents: int
    web_search: int
    deep_analysis: int
    quick_mode: int


@dataclass(frozen=True, slots=True)
class AgentPriceBreakdown:
    base: int
    extras: tuple[tuple[str, int], ...]
    total: int


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
    MODEL_PRICE_SEEDANCE_20_VIDEO_PER_SECOND_KEY: "Видео: Seedance 2.0 (база за 1 сек.)",
    MODEL_PRICE_SEEDANCE_20_TURBO_VIDEO_PER_SECOND_KEY: "Видео: Seedance 2.0 Turbo (база за 1 сек.)",
    MODEL_PRICE_HAPPY_HORSE_10_VIDEO_PER_SECOND_KEY: "Видео: Happy Horse 1.0 (база за 1 сек.)",
    MODEL_PRICE_WAN_27_VIDEO_PER_SECOND_KEY: "Видео: WAN 2.7 (база за 1 сек.)",
    MODEL_PRICE_WAN_22_SPICY_VIDEO_PER_SECOND_KEY: "Видео: WAN 2.2 Spicy (база за 1 сек.)",
    MODEL_PRICE_KLING_30_VIDEO_PER_SECOND_KEY: "Видео: Kling 3.0 (база за 1 сек.)",
    MODEL_PRICE_KLING_O3_VIDEO_PER_SECOND_KEY: "Видео: Kling O3 (база за 1 сек.)",
    MODEL_PRICE_VEO_31_LITE_VIDEO_PER_SECOND_KEY: "Видео: Veo 3.1 Lite (база за 1 сек.)",
    MODEL_PRICE_GROK_IMAGINE_VIDEO_PER_SECOND_KEY: "Видео: Grok Imagine (база за 1 сек.)",
    MODEL_PRICE_WEARAI_AGENT_KEY: "Агент WeaRai: базовый запрос",
    MODEL_PRICE_WEARAI_AGENT_MEMORY_KEY: "Агент WeaRai: память диалога",
    MODEL_PRICE_WEARAI_AGENT_DOCUMENTS_KEY: "Агент WeaRai: документы",
    MODEL_PRICE_WEARAI_AGENT_WEB_SEARCH_KEY: "Агент WeaRai: веб-поиск",
    MODEL_PRICE_WEARAI_AGENT_DEEP_ANALYSIS_KEY: "Агент WeaRai: глубокий анализ",
    MODEL_PRICE_WEARAI_AGENT_QUICK_MODE_KEY: "Агент WeaRai: быстрый режим",
}

LAUNCH_DAILY_LIMIT_KEY = "launch_daily_limit"
AGENT_DAILY_FREE_LIMIT_KEY = "agent_daily_free_limit"


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


async def get_agent_daily_free_limit(session: AsyncSession) -> int:
    return await _get_int_setting(session, AGENT_DAILY_FREE_LIMIT_KEY, 0)


async def set_agent_daily_free_limit(session: AsyncSession, value: int) -> None:
    await _set_int_setting(session, AGENT_DAILY_FREE_LIMIT_KEY, int(value))


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


async def get_agent_request_pricing(session: AsyncSession) -> AgentRequestPricing:
    await ensure_model_pricing_settings(session)
    return AgentRequestPricing(
        base=await _get_int_setting(session, MODEL_PRICE_WEARAI_AGENT_KEY, 5),
        memory=await _get_int_setting(session, MODEL_PRICE_WEARAI_AGENT_MEMORY_KEY, 2),
        documents=await _get_int_setting(session, MODEL_PRICE_WEARAI_AGENT_DOCUMENTS_KEY, 2),
        web_search=await _get_int_setting(session, MODEL_PRICE_WEARAI_AGENT_WEB_SEARCH_KEY, 1),
        deep_analysis=await _get_int_setting(
            session,
            MODEL_PRICE_WEARAI_AGENT_DEEP_ANALYSIS_KEY,
            1,
        ),
        quick_mode=await _get_int_setting(
            session,
            MODEL_PRICE_WEARAI_AGENT_QUICK_MODE_KEY,
            1,
        ),
    )


def build_agent_price_breakdown(
    pricing: AgentRequestPricing,
    *,
    memory_enabled: bool,
    documents_enabled: bool,
    web_search_enabled: bool,
    deep_analysis_enabled: bool,
    quick_mode_enabled: bool,
) -> AgentPriceBreakdown:
    extras: list[tuple[str, int]] = []
    if memory_enabled and pricing.memory > 0:
        extras.append(("память диалога", int(pricing.memory)))
    if documents_enabled and pricing.documents > 0:
        extras.append(("документы", int(pricing.documents)))
    if web_search_enabled and pricing.web_search > 0:
        extras.append(("веб-поиск", int(pricing.web_search)))
    if deep_analysis_enabled and pricing.deep_analysis > 0:
        extras.append(("глубокий анализ", int(pricing.deep_analysis)))
    if quick_mode_enabled and pricing.quick_mode > 0:
        extras.append(("быстрый режим", int(pricing.quick_mode)))
    total = int(pricing.base) + sum(int(amount) for _, amount in extras)
    return AgentPriceBreakdown(
        base=int(pricing.base),
        extras=tuple(extras),
        total=total,
    )


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
