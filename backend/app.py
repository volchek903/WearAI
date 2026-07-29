from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.bootstrap import initialize_application_state, setup_logging
from app.db import engine, session_factory
from app.web.catalog import build_public_catalog
from app.web.generation import (
    WebGenerationError,
    chat_with_agent_for_web,
    generate_music_mode,
    generate_photo_mode,
    generate_video_mode,
    store_agent_document_for_web,
)
from app.web.session import build_web_profile, generate_client_id


class SessionRequest(BaseModel):
    client_id: str | None = None
    username: str | None = None


class AgentChatRequest(BaseModel):
    client_id: str
    text: str = Field(min_length=1)
    toggles: dict[str, Any] | None = None


class MusicRequest(BaseModel):
    client_id: str
    selected_tags: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    section_texts: dict[str, str] = Field(default_factory=dict)
    instrumental: bool = False
    duration: int = 30
    seed: int = -1


def _generated_root() -> Path:
    raw = os.getenv("GENERATED_DIR", "").strip()
    if raw:
        return Path(raw).resolve()
    return (Path.cwd() / "_generated").resolve()


def _asset_path_to_url(path: str) -> str:
    root = _generated_root()
    current = Path(path).resolve()
    rel = current.relative_to(root)
    return f"/generated/{rel.as_posix()}"


async def _read_uploads(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    uploads: list[tuple[str, bytes]] = []
    for item in files:
        uploads.append((item.filename or "upload.bin", await item.read()))
    return uploads


def _parse_json_form(raw: str | None) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Некорректный JSON в fields_json.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="fields_json должен быть объектом.")
    return data


def _with_asset_urls(payload: dict[str, Any]) -> dict[str, Any]:
    assets = []
    for asset in payload.get("assets", []):
        current = dict(asset)
        current["url"] = _asset_path_to_url(str(asset["path"]))
        assets.append(current)
    out = dict(payload)
    out["assets"] = assets
    return out


async def get_db_session():
    async with session_factory() as session:
        yield session


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    _generated_root().mkdir(parents=True, exist_ok=True)
    async with session_factory() as session:
        await initialize_application_state(session)
    yield
    await engine.dispose()


app = FastAPI(
    title="WearAI Backend",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_generated_root().mkdir(parents=True, exist_ok=True)
app.mount("/generated", StaticFiles(directory=_generated_root()), name="generated")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/catalog")
async def catalog() -> dict[str, Any]:
    return build_public_catalog()


@app.post("/api/session")
async def create_or_get_session(
    payload: SessionRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    client_id = payload.client_id or generate_client_id()
    return await build_web_profile(
        session,
        client_id=client_id,
        username=payload.username,
    )


@app.get("/api/profile/{client_id}")
async def profile(
    client_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    return await build_web_profile(session, client_id=client_id)


@app.post("/api/generate/photo")
async def generate_photo(
    client_id: str = Form(...),
    mode_id: str = Form(...),
    fields_json: str = Form("{}"),
    files: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    fields = _parse_json_form(fields_json)
    uploads = await _read_uploads(files)
    try:
        result = await generate_photo_mode(
            session,
            client_id=client_id,
            mode_id=mode_id,
            fields=fields,
            uploads=uploads,
        )
        profile_data = await build_web_profile(session, client_id=client_id)
        return JSONResponse(
            {
                "result": _with_asset_urls(result),
                "profile": profile_data,
            }
        )
    except WebGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/generate/video")
async def generate_video(
    client_id: str = Form(...),
    mode_id: str = Form(...),
    fields_json: str = Form("{}"),
    files: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    fields = _parse_json_form(fields_json)
    uploads = await _read_uploads(files)
    try:
        result = await generate_video_mode(
            session,
            client_id=client_id,
            mode_id=mode_id,
            fields=fields,
            uploads=uploads,
        )
        profile_data = await build_web_profile(session, client_id=client_id)
        return JSONResponse(
            {
                "result": _with_asset_urls(result),
                "profile": profile_data,
            }
        )
    except WebGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/generate/music")
async def generate_music(
    payload: MusicRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        result = await generate_music_mode(
            session,
            client_id=payload.client_id,
            fields=payload.model_dump(),
        )
        profile_data = await build_web_profile(session, client_id=payload.client_id)
        return JSONResponse(
            {
                "result": _with_asset_urls(result),
                "profile": profile_data,
            }
        )
    except WebGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agent/chat")
async def agent_chat(
    payload: AgentChatRequest,
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        result = await chat_with_agent_for_web(
            session,
            client_id=payload.client_id,
            user_text=payload.text,
            toggles=payload.toggles,
        )
        profile_data = await build_web_profile(session, client_id=payload.client_id)
        return JSONResponse(
            {
                "result": result,
                "profile": profile_data,
            }
        )
    except WebGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agent/documents")
async def agent_document_upload(
    client_id: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    try:
        result = await store_agent_document_for_web(
            session,
            client_id=client_id,
            file_name=file.filename,
            mime_type=file.content_type,
            data=await file.read(),
        )
        return JSONResponse({"result": result})
    except WebGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
