from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.repository.app_settings import (
    MODEL_PRICE_GROK_IMAGINE_VIDEO_PER_SECOND_KEY,
    MODEL_PRICE_HAPPY_HORSE_10_VIDEO_PER_SECOND_KEY,
    MODEL_PRICE_KLING_30_VIDEO_PER_SECOND_KEY,
    MODEL_PRICE_KLING_O3_VIDEO_PER_SECOND_KEY,
    MODEL_PRICE_SEEDANCE_20_TURBO_VIDEO_PER_SECOND_KEY,
    MODEL_PRICE_SEEDANCE_20_VIDEO_PER_SECOND_KEY,
    MODEL_PRICE_VEO_31_LITE_VIDEO_PER_SECOND_KEY,
    MODEL_PRICE_WAN_22_SPICY_VIDEO_PER_SECOND_KEY,
    MODEL_PRICE_WAN_27_VIDEO_PER_SECOND_KEY,
)


@dataclass(frozen=True, slots=True)
class VideoResolutionOption:
    value: str
    provider_cost_per_second_usd: Decimal


@dataclass(frozen=True, slots=True)
class VideoModelConfig:
    model_id: str
    title: str
    endpoint: str
    pricing_model_key: str
    blurb: str
    features: tuple[str, ...]
    input_notes: tuple[str, ...]
    min_images: int
    max_images: int
    end_image_field: str | None
    duration_options: tuple[int, ...]
    resolution_options: tuple[VideoResolutionOption, ...]
    aspect_ratio_options: tuple[str, ...] = ()
    prompt_required: bool = True
    supports_negative_prompt: bool = False
    supports_seed: bool = False
    supports_cfg_scale: bool = False
    cfg_scale_options: tuple[str, ...] = ()
    supports_sound: bool = False
    sound_multiplier: Decimal = Decimal("1")
    supports_generate_audio: bool = False
    supports_web_search: bool = False
    supports_shot_type: bool = False
    shot_type_options: tuple[str, ...] = ("intelligent", "customize")

    @property
    def supports_resolution(self) -> bool:
        return len(self.resolution_options) > 1

    def provider_cost_per_second(self, *, resolution: str, sound_enabled: bool) -> Decimal:
        selected = next(
            (item for item in self.resolution_options if item.value == resolution),
            self.resolution_options[0],
        )
        rate = selected.provider_cost_per_second_usd
        if sound_enabled and self.supports_sound:
            rate *= self.sound_multiplier
        return rate


VIDEO_MODEL_CATALOG: tuple[VideoModelConfig, ...] = (
    VideoModelConfig(
        model_id="seedance_20",
        title="Seedance 2.0",
        endpoint="bytedance/seedance-2.0/image-to-video",
        pricing_model_key=MODEL_PRICE_SEEDANCE_20_VIDEO_PER_SECOND_KEY,
        blurb="Кинематографичная image-to-video модель с нативным аудио, хорошей стабильностью движения и гибкими aspect ratio.",
        features=(
            "🎞 Качественная анимация по одному стартовому кадру",
            "🖼 Можно добавить финальный кадр для контролируемого завершения сцены",
            "🔊 Умеет генерировать нативное аудио",
            "🌐 Поддерживает web search toggle",
        ),
        input_notes=(
            "1 обязательное фото, второе фото можно отправить как финальный кадр",
            "Длительность 4–15 сек",
            "Разрешение 480p / 720p / 1080p",
            "Aspect ratio: 16:9, 9:16, 4:3, 3:4, 1:1, 21:9",
        ),
        min_images=1,
        max_images=2,
        end_image_field="last_image",
        duration_options=(4, 5, 6, 8, 10, 12, 15),
        resolution_options=(
            VideoResolutionOption("480p", Decimal("0.12")),
            VideoResolutionOption("720p", Decimal("0.24")),
            VideoResolutionOption("1080p", Decimal("0.60")),
        ),
        aspect_ratio_options=("16:9", "9:16", "4:3", "3:4", "1:1", "21:9"),
        supports_generate_audio=True,
        supports_web_search=True,
    ),
    VideoModelConfig(
        model_id="seedance_20_turbo",
        title="Seedance 2.0 Turbo",
        endpoint="bytedance/seedance-2.0/image-to-video-turbo",
        pricing_model_key=MODEL_PRICE_SEEDANCE_20_TURBO_VIDEO_PER_SECOND_KEY,
        blurb="Turbo-версия Seedance 2.0: быстрее, дешевле стандартной HD-анимации, но с тем же director-style управлением.",
        features=(
            "⚡ Turbo-режим для быстрого HD-результата",
            "🖼 Можно добавить финальный кадр",
            "🔊 Генерация нативного аудио",
            "🌐 Поддержка web search toggle",
        ),
        input_notes=(
            "1 обязательное фото, второе фото можно отправить как финальный кадр",
            "Длительность 4–15 сек",
            "Разрешение 720p / 1080p",
            "Aspect ratio: 16:9, 9:16, 4:3, 3:4, 1:1, 21:9",
        ),
        min_images=1,
        max_images=2,
        end_image_field="last_image",
        duration_options=(4, 5, 6, 8, 10, 12, 15),
        resolution_options=(
            VideoResolutionOption("720p", Decimal("0.14")),
            VideoResolutionOption("1080p", Decimal("0.15")),
        ),
        aspect_ratio_options=("16:9", "9:16", "4:3", "3:4", "1:1", "21:9"),
        supports_generate_audio=True,
        supports_web_search=True,
    ),
    VideoModelConfig(
        model_id="happy_horse_10",
        title="Happy Horse 1.0",
        endpoint="alibaba/happyhorse-1.0/image-to-video",
        pricing_model_key=MODEL_PRICE_HAPPY_HORSE_10_VIDEO_PER_SECOND_KEY,
        blurb="Alibaba-модель для плавной cinematic image-to-video анимации с хорошим удержанием объекта и простым набором параметров.",
        features=(
            "🎥 Плавное движение камеры и стабильный subject",
            "🪄 Простой набор параметров без перегруза",
            "🔁 Seed для повторяемых результатов",
        ),
        input_notes=(
            "1 фото",
            "Длительность 3–15 сек",
            "Разрешение 720p / 1080p",
        ),
        min_images=1,
        max_images=1,
        end_image_field=None,
        duration_options=(3, 5, 8, 10, 15),
        resolution_options=(
            VideoResolutionOption("720p", Decimal("0.14")),
            VideoResolutionOption("1080p", Decimal("0.28")),
        ),
        supports_seed=True,
    ),
    VideoModelConfig(
        model_id="wan_27",
        title="WAN 2.7",
        endpoint="alibaba/wan-2.7/image-to-video",
        pricing_model_key=MODEL_PRICE_WAN_27_VIDEO_PER_SECOND_KEY,
        blurb="Сильная image-to-video модель Alibaba с first/last frame control, optional audio sync и prompt expansion.",
        features=(
            "🎬 Плавная cinematic-анимация по фото",
            "🖼 Можно задать финальный кадр",
            "🚫 Поддерживает negative prompt",
            "🎚 Seed и prompt expansion",
        ),
        input_notes=(
            "1 обязательное фото, второе фото можно отправить как финальный кадр",
            "Длительность 5 / 10 / 15 сек",
            "Разрешение 720p / 1080p",
        ),
        min_images=1,
        max_images=2,
        end_image_field="last_image",
        duration_options=(5, 10, 15),
        resolution_options=(
            VideoResolutionOption("720p", Decimal("0.10")),
            VideoResolutionOption("1080p", Decimal("0.15")),
        ),
        supports_negative_prompt=True,
        supports_seed=True,
    ),
    VideoModelConfig(
        model_id="wan_22_spicy",
        title="WAN 2.2 Spicy",
        endpoint="wavespeed-ai/wan-2.2-spicy/image-to-video",
        pricing_model_key=MODEL_PRICE_WAN_22_SPICY_VIDEO_PER_SECOND_KEY,
        blurb="Экспрессивная short-form модель для яркого движения и стилизованной анимации по одному изображению.",
        features=(
            "🔥 Выразительная motion-динамика",
            "🎨 Хорошо подходит для stylized / anime / painterly look",
            "🔁 Поддерживает seed",
        ),
        input_notes=(
            "1 фото",
            "Длительность 5 или 8 сек",
            "Разрешение 480p / 720p",
        ),
        min_images=1,
        max_images=1,
        end_image_field=None,
        duration_options=(5, 8),
        resolution_options=(
            VideoResolutionOption("480p", Decimal("0.03")),
            VideoResolutionOption("720p", Decimal("0.06")),
        ),
        supports_seed=True,
    ),
    VideoModelConfig(
        model_id="kling_30",
        title="Kling 3.0",
        endpoint="kwaivgi/kling-v3.0-std/image-to-video",
        pricing_model_key=MODEL_PRICE_KLING_30_VIDEO_PER_SECOND_KEY,
        blurb="Универсальная Kling 3.0 Standard для image-to-video с optional sound, negative prompt и продвинутым motion control через prompt.",
        features=(
            "🎥 Хорошее качество движения при умеренной цене",
            "🔊 Можно включить генерацию синхронного звука",
            "🚫 Поддерживает negative prompt",
            "🎚 Есть cfg_scale и shot_type",
        ),
        input_notes=(
            "1 обязательное фото, второе фото можно отправить как финальный кадр",
            "Длительность 3 / 5 / 10 / 15 сек",
            "Без выбора resolution на этом endpoint",
        ),
        min_images=1,
        max_images=2,
        end_image_field="end_image",
        duration_options=(3, 5, 10, 15),
        resolution_options=(VideoResolutionOption("default", Decimal("0.084")),),
        supports_negative_prompt=True,
        supports_cfg_scale=True,
        cfg_scale_options=("0.5", "0.7", "1.0"),
        supports_sound=True,
        sound_multiplier=Decimal("1.5"),
        supports_shot_type=True,
    ),
    VideoModelConfig(
        model_id="kling_o3",
        title="Kling O3",
        endpoint="kwaivgi/kling-video-o3-std/image-to-video",
        pricing_model_key=MODEL_PRICE_KLING_O3_VIDEO_PER_SECOND_KEY,
        blurb="Новая O3-линейка Kling с более сильной MVL-логикой, sound toggle и scene progression через prompt.",
        features=(
            "🧠 O3-generation с сильной визуальной связностью",
            "🔊 Можно включить генерацию звука",
            "🖼 Поддержка финального кадра",
            "🎛 Доступен shot_type",
        ),
        input_notes=(
            "1 обязательное фото, второе фото можно отправить как финальный кадр",
            "Длительность 3 / 5 / 10 / 15 сек",
            "Без выбора resolution на этом endpoint",
        ),
        min_images=1,
        max_images=2,
        end_image_field="end_image",
        duration_options=(3, 5, 10, 15),
        resolution_options=(VideoResolutionOption("default", Decimal("0.084")),),
        supports_sound=True,
        sound_multiplier=Decimal("1.3333333333"),
        supports_shot_type=True,
    ),
    VideoModelConfig(
        model_id="veo_31_lite",
        title="Veo 3.1 Lite",
        endpoint="google/veo3.1-lite/image-to-video",
        pricing_model_key=MODEL_PRICE_VEO_31_LITE_VIDEO_PER_SECOND_KEY,
        blurb="Легкая версия Veo 3.1 для качественной image-to-video генерации с 720p/1080p и поддержкой portrait/landscape.",
        features=(
            "🎬 Сильная cinematic image-to-video анимация",
            "📐 Поддержка 16:9 и 9:16",
            "🚫 Negative prompt и seed",
        ),
        input_notes=(
            "1 фото",
            "Длительность 4 / 6 / 8 сек",
            "Разрешение 720p / 1080p",
            "Aspect ratio: 16:9 или 9:16",
        ),
        min_images=1,
        max_images=1,
        end_image_field=None,
        duration_options=(4, 6, 8),
        resolution_options=(
            VideoResolutionOption("720p", Decimal("0.05")),
            VideoResolutionOption("1080p", Decimal("0.08")),
        ),
        aspect_ratio_options=("16:9", "9:16"),
        supports_negative_prompt=True,
        supports_seed=True,
    ),
    VideoModelConfig(
        model_id="grok_imagine",
        title="Grok Imagine",
        endpoint="x-ai/grok-imagine-video/image-to-video",
        pricing_model_key=MODEL_PRICE_GROK_IMAGINE_VIDEO_PER_SECOND_KEY,
        blurb="Быстрая image-to-video модель xAI для оживления фото с натуральным движением и простыми настройками.",
        features=(
            "⚡ Быстрый запуск без перегруза параметрами",
            "🎞 Длительность 6 или 10 сек",
            "📺 Разрешение 480p / 720p",
        ),
        input_notes=(
            "1 фото",
            "Длительность 6 или 10 сек",
            "Разрешение 480p / 720p",
        ),
        min_images=1,
        max_images=1,
        end_image_field=None,
        duration_options=(6, 10),
        resolution_options=(
            VideoResolutionOption("480p", Decimal("0.05")),
            VideoResolutionOption("720p", Decimal("0.05")),
        ),
    ),
)

VIDEO_MODELS_BY_ID = {item.model_id: item for item in VIDEO_MODEL_CATALOG}


def get_video_model(model_id: str) -> VideoModelConfig | None:
    return VIDEO_MODELS_BY_ID.get((model_id or "").strip())
