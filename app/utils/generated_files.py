from __future__ import annotations

import os
import time
import uuid
from pathlib import Path


def _root_dir() -> Path:
    # можно переопределить в .env: GENERATED_DIR=/abs/path
    env = os.getenv("GENERATED_DIR", "").strip()
    if env:
        return Path(env)
    return Path.cwd() / "_generated"  # в корне проекта


def save_generated_image_bytes(
    *,
    img_bytes: bytes,
    filename: str,
    scenario: str,
    tg_id: int,
    keep_last: int = 20,
) -> str:
    """
    Сохраняем изображение на диск и возвращаем абсолютный путь.
    Храним последние keep_last файлов на пользователя/сценарий.
    """
    root = _root_dir()
    out_dir = root / scenario / str(tg_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(filename).suffix or ".png"
    ts = int(time.time() * 1000)
    out_name = f"{ts}_{uuid.uuid4().hex[:8]}{ext}"
    out_path = out_dir / out_name
    out_path.write_bytes(img_bytes)

    # лёгкая чистка старых
    try:
        files = sorted(out_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[keep_last:]:
            p.unlink(missing_ok=True)
    except Exception:
        pass

    return str(out_path.resolve())
