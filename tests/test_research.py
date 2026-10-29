# ruff: noqa: E501
"""Research agent: tool loop, evidence guard, citation whitelist. No network."""

from __future__ import annotations

import json

import pytest

from film_shot_agent.adapters import llm as llm_adapter
from film_shot_agent.adapters import search as search_adapter
from film_shot_agent.core.config import Settings
from film_shot_agent.services import research as service

DOUBAN = "https://movie.douban.com/subject/3541415/"
IMDB = "https://www.imdb.com/title/tt1375666/"
BILI = "https://www.bilibili.com/bangumi/play/ep123"
PIRATE = "https://pirate.example/film"
FAKE = "https://fake.example/invented"

HITS = [
    search_adapter.SearchHit(
        "盗梦空间 - 豆瓣电影", DOUBAN, "盗梦空间 Inception (2010) 9.4 分，观众评价很高。"
    ),
    search_adapter.SearchHit("Inception - IMDb", IMDB, "8.8/10 · A thief steals secrets."),
    search_adapter.SearchHit("盗梦空间 在线观看", BILI, "盗梦空间 免费观看，官方平台。"),
]

COMPOSE = {
    "answer": "《盗梦空间》口碑很好，豆瓣 9.4，IMDb 8.8。",
    "intent": "rating",
    "titles": [
        {
            "name": "盗梦空间",
            "original_name": "Inception",
            "year": 2010,
            "kind": "电影",
            "confidence": "high",
            "ratings": [
                {"source": "豆瓣", "score": "9.4", "out_of": "10", "url": DOUBAN, "note": "搜索摘要"},
                {"source": "IMDb", "score": "8.8", "out_of": "10", "url": IMDB},
                {"source": "豆瓣", "score": "9.9", "out_of": "10", "url": DOUBAN},
            ],
            "watch": [
                {"platform": "哔哩哔哩", "access": "可能免费", "url": BILI, "note": "官方"},
                {"platform": "盗版站", "access": "免费", "url": PIRATE},
            ],
            "reviews": [
                {"source": "豆瓣", "summary": "结构精巧，值得二刷。", "url": DOUBAN},
                {"source": "无链接", "summary": "这条没有来源，应被丢弃。", "url": ""},
            ],
        }
    ],
    "citations": [
        {"title": "豆瓣", "url": DOUBAN},
        {"title": "编造", "url": FAKE},
    ],
    "caveats": ["评分会变。"],
    "followups": ["再找一部类似的"],
}


class FakeLLM:
    def __init__(self, *, tool_calls=None, compose=None):
        self.tool_calls = list(tool_calls or [])
        self.compose = compose or COMPOSE
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        if kwargs.get("json_mode"):
            return llm_adapter.ChatResult(
                content=json.dumps(self.compose, ensure_ascii=False),
                prompt_tokens=10,
                completion_tokens=20,
            )
        if self.tool_calls:
            return llm_adapter.ChatResult(tool_calls=[self.tool_calls.pop(0)])
        return llm_adapter.ChatResult(content="", prompt_tokens=5, completion_tokens=1)


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
    }
    values.update(overrides)
    return Settings(**values)


def fake_search(query, limit=6):
    return HITS[:limit]


def test_agent_runs_tools_and_drops_unbacked_claims(session):
    llm = FakeLLM(
        tool_calls=[
            llm_adapter.ToolCall("c1", "where_to_watch", {"title": "盗梦空间"}),
            llm_adapter.ToolCall("c2", "search_web", {"query": "盗梦空间 豆瓣 评分"}),
        ]
    )
    out = service.research(session, "盗梦空间好看吗，在哪看？", settings=settings(), llm=llm, search=fake_search)

    assert out["intent"] == "rating"
    assert out["answer"].startswith("《盗梦空间》")
    assert {step["tool"] for step in out["trace"]} == {"where_to_watch", "search_web"}

    title = out["titles"][0]
    assert {rating["score"] for rating in title["ratings"]} == {"9.4", "8.8"}
    assert title["watch"] == [
        {"platform": "哔哩哔哩", "access": "可能免费", "url": BILI, "note": "搜索结果，是否免费以页面为准"}
    ]
    assert [review["url"] for review in title["reviews"]] == [DOUBAN]

    urls = {item["url"] for item in out["citations"]}
    assert FAKE not in urls and PIRATE not in urls
    assert {DOUBAN, IMDB, BILI} <= urls
    assert any("证据不足" in caveat for caveat in out["caveats"])


def test_forces_at_least_one_web_search(session):
    llm = FakeLLM(tool_calls=[], compose={"answer": "没查到", "intent": "other", "titles": [], "citations": []})
    out = service.research(session, "最近有什么好看的电影", settings=settings(), llm=llm, search=fake_search)
    assert [step["tool"] for step in out["trace"]] == ["search_web"]
    assert out["intent"] == "other"
    assert any("公开网页" in caveat for caveat in out["caveats"])


def test_missing_key_is_unavailable(session):
    with pytest.raises(service.ResearchUnavailable):
        service.research(session, "找部片", settings=settings(llm_api_key=""))


def test_quote_tool_hits_local_library(session):
    ctx = service.ResearchContext(
        session=session,
        settings=settings(),
        llm=FakeLLM(),
        search=lambda query, limit=6: [],
    )
    payload = service._run_tool("search_quote", {"quote": "robot hand"}, ctx)
    assert payload["ok"] is True
    assert payload["local"][0]["title"] == "阿尔法"
    assert payload["local"][0]["shot_id"]


def test_scene_tool_only_returns_candidates(session):
    llm = FakeLLM(
        tool_calls=[
            llm_adapter.ToolCall("c1", "identify_scene", {"description": "男人在雨中跳舞"}),
        ],
        compose={
            "answer": "不确定，可能是《雨中曲》。",
            "intent": "scene",
            "titles": [{"name": "雨中曲", "year": 1952, "confidence": "low"}],
            "citations": [{"title": "来源", "url": DOUBAN}],
        },
    )
    out = service.research(session, "哪部电影里男主角在雨中跳舞？", settings=settings(), llm=llm, search=fake_search)
    assert out["intent"] == "scene"
    assert out["titles"][0]["confidence"] == "low"
    assert any("截图" in caveat for caveat in out["caveats"])


def test_tmdb_rating_is_attached_when_composer_omits_it(session):
    ctx = service.ResearchContext(
        session=session,
        settings=settings(),
        llm=FakeLLM(),
        search=fake_search,
    )
    ctx.record_rating(
        {
            "source": "TMDB",
            "score": 8.4,
            "out_of": 10,
            "url": "https://www.themoviedb.org/movie/27205",
            "note": "",
        },
        "盗梦空间",
    )
    out = service._normalise(
        {"answer": "好看", "intent": "rating", "titles": [{"name": "盗梦空间"}]},
        ctx,
        "盗梦空间好看吗",
    )
    assert out["titles"][0]["ratings"] == [
        {
            "source": "TMDB",
            "score": "8.4",
            "out_of": "10",
            "url": "https://www.themoviedb.org/movie/27205",
            "note": "TMDB 结构化数据",
        }
    ]


def test_sequel_ratings_do_not_cross_attach(session):
    assert not service._names_match("沙丘", "沙丘2")
    assert service._names_match("9号秘事", "9号秘事 第一季")
    ctx = service.ResearchContext(
        session=session,
        settings=settings(),
        llm=FakeLLM(),
        search=fake_search,
    )
    dune1 = "https://www.themoviedb.org/movie/438631"
    dune2 = "https://www.themoviedb.org/movie/693134"
    ctx.record_rating({"source": "TMDB", "score": 7.8, "out_of": 10, "url": dune1}, "沙丘")
    ctx.record_rating({"source": "TMDB", "score": 8.1, "out_of": 10, "url": dune2}, "沙丘2")
    raw = {
        "answer": "沙丘2 略高",
        "intent": "rating",
        "titles": [
            {
                "name": "沙丘2",
                "ratings": [
                    {"source": "TMDB", "score": "8.1", "out_of": "10", "url": dune2},
                    {"source": "TMDB", "score": "7.8", "out_of": "10", "url": dune1},
                ],
            },
            {
                "name": "沙丘",
                "ratings": [
                    {"source": "TMDB", "score": "7.8", "out_of": "10", "url": dune1},
                    {"source": "TMDB", "score": "8.1", "out_of": "10", "url": dune2},
                ],
            },
        ],
    }
    out = service._normalise(raw, ctx, "沙丘2 和沙丘1 哪个评分高")
    assert [r["url"] for r in out["titles"][0]["ratings"]] == [dune2]
    assert [r["url"] for r in out["titles"][1]["ratings"]] == [dune1]


def test_enrichment_adds_a_tmdb_rating_without_the_composer(session, monkeypatch):
    ctx = service.ResearchContext(
        session=session,
        settings=settings(tmdb_api_key="test-tmdb"),
        llm=FakeLLM(),
        search=fake_search,
    )
    payload = {
        "answer": "好看",
        "titles": [{"name": "肖申克的救赎", "year": 1994, "ratings": [], "watch": []}],
        "citations": [],
    }
    tmdb_url = "https://www.themoviedb.org/movie/278"
    monkeypatch.setattr(
        service.tmdb_adapter,
        "lookup",
        lambda *args, **kwargs: {
            "name": "肖申克的救赎",
            "original_name": "The Shawshank Redemption",
            "url": tmdb_url,
            "ratings": [
                {"source": "TMDB", "score": 8.7, "out_of": 10, "url": tmdb_url}
            ],
            "watch": [],
        },
    )
    service._enrich_missing_titles(payload, ctx)
    assert payload["titles"][0]["ratings"] == [
        {
            "source": "TMDB",
            "score": "8.7",
            "out_of": "10",
            "url": tmdb_url,
            "note": "TMDB 结构化数据",
        }
    ]
    assert payload["citations"] == [{"title": "TMDB · 肖申克的救赎", "url": tmdb_url}]


def test_extract_score_from_snippets():
    assert service._extract_score("豆瓣评分 8.6 分，评价人数很多") == "8.6"
    assert service._extract_score("IMDb 8.8/10 · A thief") == "8.8"
    assert service._extract_score("2024 年上映，片长 134 分钟") == ""


def test_merge_ratings_prefers_item_page_and_one_per_source():
    items = [
        {"source": "豆瓣", "score": "8.1", "url": "https://movie.douban.com/review/1/"},
        {"source": "豆瓣", "score": "8.6", "url": "https://movie.douban.com/subject/34874646/"},
        {"source": "TMDB", "score": "8.4", "url": "https://www.themoviedb.org/movie/1"},
    ]
    merged = service._merge_ratings(items)
    assert {(r["source"], r["score"]) for r in merged} == {("豆瓣", "8.6"), ("TMDB", "8.4")}
