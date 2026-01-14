from __future__ import annotations

from dataclasses import dataclass

ASPECT_RATIOS: list[str] = [
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
    "auto",
]

RESOLUTIONS: list[str] = ["1K", "2K"]  # "4K"

OUTPUT_FORMATS: list[str] = ["png", "jpg"]


@dataclass(frozen=True)
class DefaultPhotoSettings:
    aspect_ratio: str = "1:1"
    resolution: str = "2K"
    output_format: str = "png"


DEFAULT_PHOTO_SETTINGS = DefaultPhotoSettings()


def next_in_cycle(current: str, options: list[str]) -> str:
    if not options:
        return current
    try:
        i = options.index(current)
    except ValueError:
        return options[0]
    return options[(i + 1) % len(options)]
