from __future__ import annotations

from collections.abc import Sequence

from app.core.video_models import VIDEO_MODEL_CATALOG, VideoModelConfig
from app.handlers.car_in_hand import HAND_OPTIONS
from app.handlers.gpt_image_2 import (
    GPT_IMAGE_2_EDIT_MAX_IMAGES,
    GPT_IMAGE_2_EDIT_RESOLUTION_OPTIONS,
    GPT_IMAGE_2_QUALITY_OPTIONS,
    GPT_IMAGE_2_TEXT_RESOLUTION_OPTIONS,
)
from app.handlers.music_ace_step import DURATION_OPTIONS, PRESET_STRUCTURES, TAG_CATEGORIES
from app.handlers.seedream_lite import SEEDREAM_FORMAT_OPTIONS, SEEDREAM_SIZE_OPTIONS


def _options(values: Sequence[str]) -> list[dict[str, str]]:
    return [{"label": str(value), "value": str(value)} for value in values]


def _select_field(
    *,
    name: str,
    label: str,
    values: Sequence[str],
    required: bool = False,
    default: str | None = None,
    help_text: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "label": label,
        "type": "select",
        "required": required,
        "default": default,
        "help_text": help_text,
        "options": _options(values),
    }


def _text_field(
    *,
    name: str,
    label: str,
    required: bool = False,
    multiline: bool = False,
    placeholder: str | None = None,
    help_text: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "label": label,
        "type": "textarea" if multiline else "text",
        "required": required,
        "placeholder": placeholder,
        "help_text": help_text,
    }


def _number_field(
    *,
    name: str,
    label: str,
    required: bool = False,
    min_value: int | None = None,
    max_value: int | None = None,
    default: int | None = None,
    help_text: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "label": label,
        "type": "number",
        "required": required,
        "min": min_value,
        "max": max_value,
        "default": default,
        "help_text": help_text,
    }


def _video_fields(model: VideoModelConfig) -> list[dict[str, object]]:
    fields: list[dict[str, object]] = [
        _text_field(
            name="prompt",
            label="Промпт",
            required=bool(model.prompt_required),
            multiline=True,
            placeholder="Опиши движение, камеру, свет и атмосферу.",
        ),
        _select_field(
            name="duration",
            label="Длительность",
            values=[str(item) for item in model.duration_options],
            required=True,
            default=str(model.duration_options[0]),
        ),
    ]
    if model.supports_resolution:
        fields.append(
            _select_field(
                name="resolution",
                label="Разрешение",
                values=[item.value for item in model.resolution_options],
                required=True,
                default=model.resolution_options[0].value,
            )
        )
    if model.aspect_ratio_options:
        fields.append(
            _select_field(
                name="aspect_ratio",
                label="Соотношение сторон",
                values=model.aspect_ratio_options,
                required=True,
                default=model.aspect_ratio_options[0],
            )
        )
    if model.supports_negative_prompt:
        fields.append(
            _text_field(
                name="negative_prompt",
                label="Negative prompt",
                multiline=True,
                placeholder="blur, artifacts, extra limbs...",
            )
        )
    if model.supports_sound:
        fields.append(
            _select_field(
                name="sound",
                label="Звук",
                values=("false", "true"),
                default="false",
            )
        )
    if model.supports_generate_audio:
        fields.append(
            _select_field(
                name="generate_audio",
                label="Генерация аудио",
                values=("true", "false"),
                default="true",
            )
        )
    if model.supports_web_search:
        fields.append(
            _select_field(
                name="enable_web_search",
                label="Web search",
                values=("false", "true"),
                default="false",
            )
        )
    if model.supports_cfg_scale:
        fields.append(
            _select_field(
                name="cfg_scale",
                label="CFG scale",
                values=model.cfg_scale_options,
                default=model.cfg_scale_options[0],
            )
        )
    if model.supports_shot_type:
        fields.append(
            _select_field(
                name="shot_type",
                label="Тип кадра",
                values=model.shot_type_options,
                default=model.shot_type_options[0],
            )
        )
    if model.supports_seed:
        fields.append(
            _number_field(
                name="seed",
                label="Seed",
                default=-1,
                help_text="-1 оставляет случайный seed.",
            )
        )
    return fields


PHOTO_MODES: list[dict[str, object]] = [
    {
        "id": "nano_banana",
        "title": "Nano Banana 2",
        "kind": "photo_model",
        "description": "Редактирование по 1-8 референсам с текстовым промптом.",
        "min_files": 1,
        "max_files": 8,
        "fields": [
            _text_field(
                name="prompt",
                label="Промпт",
                required=True,
                multiline=True,
                placeholder="Опиши, что нужно получить на выходе.",
            )
        ],
    },
    {
        "id": "nano_banana_pro",
        "title": "Nano Banana Pro",
        "kind": "photo_model",
        "description": "Версия Pro для более сложных edit-задач по 1-10 фото.",
        "min_files": 1,
        "max_files": 10,
        "fields": [
            _text_field(name="prompt", label="Промпт", required=True, multiline=True)
        ],
    },
    {
        "id": "seedream_lite",
        "title": "Seedream 5 Lite",
        "kind": "photo_model",
        "description": "Генерация по тексту или edit с референсами, с настройками размера и формата.",
        "min_files": 0,
        "max_files": 10,
        "fields": [
            _text_field(name="prompt", label="Промпт", required=True, multiline=True),
            _select_field(name="size", label="Preset size", values=SEEDREAM_SIZE_OPTIONS, default="auto"),
            _number_field(name="width", label="Width", min_value=1440, max_value=4096),
            _number_field(name="height", label="Height", min_value=1440, max_value=4096),
            _select_field(name="output_format", label="Формат", values=SEEDREAM_FORMAT_OPTIONS, default="png"),
        ],
    },
    {
        "id": "seedream_45",
        "title": "Seedream 4.5",
        "kind": "photo_model",
        "description": "Text-to-image режим с preset size.",
        "min_files": 0,
        "max_files": 0,
        "fields": [
            _text_field(name="prompt", label="Промпт", required=True, multiline=True),
            _select_field(name="size", label="Preset size", values=SEEDREAM_SIZE_OPTIONS, default="auto"),
        ],
    },
    {
        "id": "wan_27",
        "title": "WAN 2.7",
        "kind": "photo_model",
        "description": "Text-to-image с кастомным размером, thinking mode и seed.",
        "min_files": 0,
        "max_files": 0,
        "fields": [
            _text_field(name="prompt", label="Промпт", required=True, multiline=True),
            _select_field(name="size", label="Preset size", values=SEEDREAM_SIZE_OPTIONS, default="auto"),
            _number_field(name="width", label="Width"),
            _number_field(name="height", label="Height"),
            _select_field(name="thinking_mode", label="Thinking mode", values=("false", "true"), default="false"),
            _number_field(name="seed", label="Seed"),
        ],
    },
    {
        "id": "gpt_image_2_edit",
        "title": "GPT Image 2 Edit",
        "kind": "photo_model",
        "description": "Edit по 1-5 входным изображениям с quality / aspect / resolution.",
        "min_files": 1,
        "max_files": GPT_IMAGE_2_EDIT_MAX_IMAGES,
        "fields": [
            _text_field(name="prompt", label="Промпт", required=True, multiline=True),
            _select_field(name="aspect_ratio", label="Aspect ratio", values=("auto", "1:1", "3:2", "2:3", "4:3", "3:4", "4:5", "5:4", "9:16", "16:9"), default="auto"),
            _select_field(name="resolution", label="Resolution", values=GPT_IMAGE_2_EDIT_RESOLUTION_OPTIONS, default="1k"),
            _select_field(name="quality", label="Quality", values=GPT_IMAGE_2_QUALITY_OPTIONS, default="medium"),
        ],
    },
    {
        "id": "gpt_image_2_text_to_image",
        "title": "GPT Image 2 Text to Image",
        "kind": "photo_model",
        "description": "Text-to-image на GPT Image 2 с 4K-режимом.",
        "min_files": 0,
        "max_files": 0,
        "fields": [
            _text_field(name="prompt", label="Промпт", required=True, multiline=True),
            _select_field(name="aspect_ratio", label="Aspect ratio", values=("1:1", "3:2", "2:3", "4:3", "3:4", "4:5", "5:4", "9:16", "16:9"), default="1:1"),
            _select_field(name="resolution", label="Resolution", values=GPT_IMAGE_2_TEXT_RESOLUTION_OPTIONS, default="1k"),
            _select_field(name="quality", label="Quality", values=GPT_IMAGE_2_QUALITY_OPTIONS, default="medium"),
        ],
    },
    {
        "id": "tryon",
        "title": "Примерить одежду",
        "kind": "photo_scenario",
        "description": "2 фото: человек и вещь. Генерирует реалистичный virtual try-on.",
        "min_files": 2,
        "max_files": 2,
        "fields": [
            _text_field(
                name="style_prompt",
                label="Инструкция",
                required=True,
                multiline=True,
                placeholder="Оставь оригинальный цвет, сделай естественную посадку...",
            )
        ],
    },
    {
        "id": "model_with_product",
        "title": "Модель с товаром",
        "kind": "photo_scenario",
        "description": "Опиши модель и способ подачи товара, затем загрузи 1-5 фото товара.",
        "min_files": 1,
        "max_files": 5,
        "fields": [
            _text_field(name="model_desc", label="Описание модели", required=True, multiline=True),
            _text_field(name="presentation_desc", label="Что сделать с товаром", required=True, multiline=True),
        ],
    },
    {
        "id": "love_is",
        "title": "Love is",
        "kind": "photo_scenario",
        "description": "Открытка в стиле Love is по 1-2 фото пары и тексту подписи.",
        "min_files": 1,
        "max_files": 2,
        "fields": [
            _text_field(name="love_text", label="Подпись Love is", required=True, multiline=False),
        ],
    },
    {
        "id": "march8",
        "title": "Поздравление с 8 Марта",
        "kind": "photo_scenario",
        "description": "Акварельное поздравление по 1-2 фото и вашему тексту.",
        "min_files": 1,
        "max_files": 2,
        "fields": [
            _text_field(name="caption_text", label="Текст под фото", required=True),
        ],
    },
    {
        "id": "car_in_hand",
        "title": "Ваша машина в руке",
        "kind": "photo_scenario",
        "description": "Миниатюра вашей машины в руке на выбранном фоне.",
        "min_files": 1,
        "max_files": 1,
        "fields": [
            _text_field(name="background", label="Описание фона", required=True),
            {
                "name": "hand_option",
                "label": "Тип руки",
                "type": "select",
                "required": True,
                "default": "male_glove",
                "options": [{"label": value, "value": key} for key, value in HAND_OPTIONS.items()],
            },
        ],
    },
    {
        "id": "radar",
        "title": "ИИ Радар",
        "kind": "photo_scenario",
        "description": "Фото людей для кадра с радаром + данные машины, номера и локации.",
        "min_files": 1,
        "max_files": 8,
        "fields": [
            _text_field(name="car", label="Машина", required=True),
            _text_field(name="plates", label="Номер", required=True),
            _text_field(name="people_action", label="Что делают люди", required=True, multiline=True),
            _text_field(name="location", label="Локация", required=True, multiline=True),
        ],
    },
    {"id": "drift_heart", "title": "Дрифт сердце", "kind": "photo_scenario", "description": "Вертикальный wallpaper с дрифтом и сердцем на льду.", "min_files": 1, "max_files": 1, "fields": []},
    {"id": "rear_view_mirror", "title": "Зеркало заднего вида", "kind": "photo_scenario", "description": "Дрифтующая машина в отражении зеркала.", "min_files": 1, "max_files": 1, "fields": []},
    {"id": "disney_family_heart", "title": "Семья в сердечке", "kind": "photo_scenario", "description": "Disney-style семейный портрет внутри сердца.", "min_files": 1, "max_files": 8, "fields": []},
    {"id": "disney_family_wall", "title": "Семья из-за стены", "kind": "photo_scenario", "description": "Disney/Pixar CGI-композиция с вертикальной стеной.", "min_files": 1, "max_files": 8, "fields": []},
    {"id": "main_defender", "title": "Мой главный защитник", "kind": "photo_scenario", "description": "Поздравительная карточка по 1-2 фото пары.", "min_files": 1, "max_files": 2, "fields": []},
    {"id": "cinema_bw", "title": "Одни в кинозале ЧБ", "kind": "photo_scenario", "description": "ЧБ cinematic сцена по 2 фото.", "min_files": 2, "max_files": 2, "fields": []},
    {"id": "second_life", "title": "Вторая жизнь для фото", "kind": "photo_scenario", "description": "Реалистичное восстановление и улучшение фото.", "min_files": 1, "max_files": 1, "fields": []},
    {"id": "feb23", "title": "23 февраля", "kind": "photo_scenario", "description": "Вертикальная поздравительная сцена по 1-2 фото.", "min_files": 1, "max_files": 2, "fields": []},
    {"id": "gta_style", "title": "GTA Style", "kind": "photo_scenario", "description": "GTA-style portrait с фирменным фоном.", "min_files": 1, "max_files": 1, "fields": []},
    {"id": "lego_style", "title": "LEGO Style", "kind": "photo_scenario", "description": "Полная LEGO-стилизация сцены.", "min_files": 1, "max_files": 1, "fields": []},
    {"id": "sims_style", "title": "Sims стиль", "kind": "photo_scenario", "description": "Встраивание человека или животного в Sims-сцену.", "min_files": 1, "max_files": 1, "fields": []},
    {"id": "glam_collage", "title": "Шикарный коллаж", "kind": "photo_scenario", "description": "Глянцевый editorial-коллаж 3:4.", "min_files": 1, "max_files": 1, "fields": []},
]


def build_video_modes() -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for model in VIDEO_MODEL_CATALOG:
        items.append(
            {
                "id": model.model_id,
                "title": model.title,
                "kind": "video_model",
                "description": model.blurb,
                "min_files": model.min_images,
                "max_files": model.max_images,
                "fields": _video_fields(model),
            }
        )
    items.extend(
        [
            {
                "id": "animate_photo",
                "title": "Оживить фото",
                "kind": "video_special",
                "description": "Быстрый image-to-video по одному фото и промпту на 5 секунд.",
                "min_files": 1,
                "max_files": 1,
                "fields": [
                    _text_field(name="prompt", label="Промпт", required=True, multiline=True),
                ],
            },
            {
                "id": "motion_control",
                "title": "Оживить фото по видео",
                "kind": "video_special",
                "description": "Фото + видео-референс + опциональный промпт.",
                "min_files": 2,
                "max_files": 2,
                "fields": [
                    _text_field(name="prompt", label="Промпт", multiline=True),
                ],
            },
        ]
    )
    return items


def build_public_catalog() -> dict[str, object]:
    return {
        "photo_modes": PHOTO_MODES,
        "video_modes": build_video_modes(),
        "music": {
            "id": "music_ace_step",
            "title": "ACE-Step Music",
            "duration_options": list(DURATION_OPTIONS),
            "tag_categories": TAG_CATEGORIES,
            "preset_structures": PRESET_STRUCTURES,
        },
        "agent": {
            "id": "wearai_agent",
            "title": "WeaRai Agent",
            "features": [
                "chat",
                "memory",
                "documents",
                "web_search",
                "deep_analysis",
                "quick_mode",
            ],
        },
    }
