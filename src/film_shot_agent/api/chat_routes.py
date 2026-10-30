"""Chat API: one dialog, no local library."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from film_shot_agent.adapters import thirtythree
from film_shot_agent.adapters.search import active_provider
from film_shot_agent.core.config import get_settings
from film_shot_agent.services import chat as chat_service

router = APIRouter()


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=300)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


@router.post("/api/chat")
def chat(payload: ChatRequest):
    text = payload.message.strip()
    if not text:
        return _error("empty_message", "问题不能为空。", 400)
    try:
        result = chat_service.chat(
            text,
            history=[turn.model_dump() for turn in payload.history],
        )
    except chat_service.ResearchUnavailable as exc:
        return _error("research_unavailable", str(exc), 503)
    except chat_service.ResearchError as exc:
        return _error("research_failed", str(exc), 502)
    except Exception:  # noqa: BLE001 - never leak internals or keys
        return _error("research_failed", "问片暂时不可用，请稍后再试。", 500)
    return result


@router.get("/api/chat/meta")
def chat_meta() -> dict:
    settings = get_settings()
    return {
        "enabled": settings.has_llm,
        "model": settings.llm_model,
        "search": active_provider(settings),
        "tmdb": settings.has_tmdb,
        "region": settings.region,
        "platforms": [
            "哔哩哔哩",
            "腾讯视频",
            "爱奇艺",
            "优酷",
            "芒果TV",
            "1905电影网",
            "搜狐视频",
            "乐视视频",
            "Netflix",
            "Prime Video",
            "Disney+",
            "Apple TV",
            "YouTube",
        ],
    }


@router.get("/api/chat/health")
def chat_health() -> dict:
    return {"ok": True, "service": "film-shot-agent-chat"}


@router.get("/api/chat/subtitles/{subtitle_id}")
def subtitle_context(subtitle_id: int):
    """The subtitle window around one line, for the 「看前后文」 panel."""
    if subtitle_id <= 0 or subtitle_id > 10**12:
        return _error("invalid_subtitle", "字幕编号不合法。", 400)
    if not get_settings().subtitle_search:
        return _error("subtitles_disabled", "字幕库未启用。", 503)
    try:
        items = thirtythree.more_subtitles(subtitle_id)
    except thirtythree.SubtitleError as exc:
        return _error("subtitles_failed", str(exc), 502)
    return {"ok": True, "items": items}


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)
