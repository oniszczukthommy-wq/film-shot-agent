# ruff: noqa: E501
"""One-dialog chat: quote → film/scene, all-platform links, history."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from film_shot_agent.adapters import llm as llm_adapter
from film_shot_agent.adapters import search as search_adapter
from film_shot_agent.core.config import Settings
from film_shot_agent.main import app
from film_shot_agent.services import chat as service

DOUBAN = "https://movie.douban.com/subject/1292052/"
YOUTUBE = "https://www.youtube.com/watch?v=abc12345"
BILI = "https://www.bilibili.com/video/BV1abc"
HITS = [
    search_adapter.SearchHit("银翼杀手 豆瓣", DOUBAN, "银翼杀手 8.7 分"),
    search_adapter.SearchHit("经典片段", YOUTUBE, "I've seen things you people wouldn't believe"),
    search_adapter.SearchHit("B站正片", BILI, "银翼杀手 免费观看"),
]
COMPOSE = {
    "answer": "这句台词出自《银翼杀手》，罗伊·巴蒂的雨中独白。",
    "intent": "quote",
    "titles": [
        {
            "name": "银翼杀手",
            "year": 1982,
            "kind": "电影",
            "confidence": "high",
            "ratings": [
                {"source": "豆瓣", "score": "8.7", "out_of": "10", "url": DOUBAN, "note": "搜索摘要"}
            ],
            "scene": {
                "quote": "我见过你们人类无法想象的事情",
                "character": "罗伊·巴蒂",
                "description": "雨中临终独白",
                "timecode": "01:47:00",
                "clip_url": YOUTUBE,
                "clip_platform": "YouTube",
                "confidence": "medium",
            },
            "watch": [
                {"platform": "哔哩哔哩", "access": "需确认", "url": BILI, "direct": True}
            ],
        }
    ],
    "citations": [],
    "caveats": [],
    "followups": ["这句台词的英文原文是什么？"],
}


class FakeLLM:
    def __init__(self, *, compose=None):
        self.i = 0
        self.compose = compose or COMPOSE
        self.seen = []

    def chat(self, messages, **kwargs):
        self.seen.append(messages)
        if kwargs.get("json_mode"):
            return llm_adapter.ChatResult(
                content=json.dumps(self.compose, ensure_ascii=False),
                prompt_tokens=1,
                completion_tokens=1,
            )
        self.i += 1
        if self.i == 1:
            return llm_adapter.ChatResult(
                tool_calls=[llm_adapter.ToolCall("1", "search_quote", {"quote": "我见过你们人类"})]
            )
        if self.i == 2:
            return llm_adapter.ChatResult(
                tool_calls=[llm_adapter.ToolCall("2", "where_to_watch", {"title": "银翼杀手"})]
            )
        return llm_adapter.ChatResult(content="")


def settings(**overrides) -> Settings:
    values = {
        "llm_api_key": "test-key",
        "llm_base_url": "http://127.0.0.1:9",
        "llm_model": "test-model",
        "llm_max_steps": 4,
        "search_provider": "duckduckgo",
        "search_api_key": "",
        "tmdb_api_key": "",
        "research_cache_ttl": 0,
        "subtitle_search": False,
    }
    values.update(overrides)
    return Settings(**values)


def fake_search(query, limit=6):
    return HITS[:limit]


def test_quote_returns_film_scene_and_all_platforms():
    out = service.chat(
        "这句台词出自哪部片？",
        settings=settings(),
        llm=FakeLLM(),
        search=fake_search,
    )
    title = out["titles"][0]
    assert title["name"] == "银翼杀手"
    assert title["ratings"][0]["score"] == "8.7"
    assert title["scene"]["clip_url"] == YOUTUBE
    assert title["scene"]["character"] == "罗伊·巴蒂"
    assert title["scene"]["timecode"] == "01:47:00"
    assert 4 <= len(title["watch"]) <= 8
    direct = {item["platform"]: item["direct"] for item in title["watch"]}
    assert direct["哔哩哔哩"] is True
    assert direct["YouTube"] is True
    assert direct["腾讯视频"] is False
    assert any("未逐帧核对" in caveat for caveat in out["caveats"])


def test_platform_links_are_safe_official_search_pages():
    ctx = service.ResearchContext(
        settings=settings(),
        llm=FakeLLM(),
        search=fake_search,
    )
    entries = service._platform_search_entries("沙丘2", ctx)
    assert len(entries) == 6
    assert all(item["direct"] is False for item in entries)
    assert all(search_adapter.safe_http_url(item["url"]) for item in entries)
    assert any("%E6%B2%99" in item["url"] for item in entries)
    assert ctx.citations


def test_clip_platform_only_accepts_video_pages():
    assert service._clip_platform(YOUTUBE) == "YouTube"
    assert service._clip_platform("https://www.bilibili.com/video/BV1abc") == "哔哩哔哩"
    assert service._clip_platform("https://www.youtube.com/results?search_query=x") == ""
    assert service._clip_platform("https://movie.douban.com/subject/1292052/") == ""


def test_history_is_trimmed_and_filtered():
    rows = [{"role": "system", "content": "x"}] + [
        {"role": "user", "content": f"问题{i}"} for i in range(10)
    ]
    cleaned = service._clean_history(rows)
    assert len(cleaned) == 6
    assert cleaned[-1]["content"] == "问题9"
    assert all(turn["role"] in {"user", "assistant"} for turn in cleaned)


def test_chat_requires_a_model_key():
    with pytest.raises(service.ResearchUnavailable):
        service.chat("找部片", settings=settings(llm_api_key=""))


def test_chat_page_and_api():
    with TestClient(app) as client:
        assert client.get("/chat").status_code == 200
        assert client.get("/api/chat/health").json()["ok"] is True
        meta = client.get("/api/chat/meta").json()
        assert "enabled" in meta
        assert "腾讯视频" in meta["platforms"]

        original = service.chat

        def fake_chat(text, history=None):
            assert text == "测试"
            return {"answer": "ok", "intent": "other", "titles": [], "citations": []}

        service.chat = fake_chat
        try:
            response = client.post("/api/chat", json={"message": "测试"})
        finally:
            service.chat = original
        assert response.status_code == 200
        assert response.json()["answer"] == "ok"


def test_subtitle_context_endpoint(monkeypatch):
    from film_shot_agent.api import chat_routes

    monkeypatch.setattr(
        chat_routes.thirtythree,
        "more_subtitles",
        lambda subtitle_id: [
            {"id": subtitle_id, "start_time": "00:03:41", "content": "Life was like a box of chocolates."}
        ],
    )
    with TestClient(app) as client:
        response = client.get("/api/chat/subtitles/3019118")
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == 3019118
    with TestClient(app) as client:
        assert client.get("/api/chat/subtitles/0").status_code == 400


def test_scene_clip_enrichment_requires_title_match():
    ctx = service.ResearchContext(
        settings=settings(),
        llm=FakeLLM(),
        search=lambda query, limit=6: [
            search_adapter.SearchHit(
                "Blade Runner - Tears in Rain clip",
                "https://www.youtube.com/watch?v=NoAzpa1x7jU",
                "final scene monologue",
            )
        ],
    )
    payload = {
        "titles": [
            {
                "name": "银翼杀手",
                "original_name": "Blade Runner",
                "scene": {"quote": "I've seen things", "clip_url": ""},
            }
        ],
        "citations": [],
    }
    service._enrich_scene_clips(payload, ctx)
    assert payload["titles"][0]["scene"]["clip_url"] == "https://www.youtube.com/watch?v=NoAzpa1x7jU"
    assert payload["titles"][0]["scene"]["clip_platform"] == "YouTube"
