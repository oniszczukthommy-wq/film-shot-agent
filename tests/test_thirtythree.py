# ruff: noqa: E501
"""33台词 subtitle adapter: signature, parsing, ranking, no network in tests."""

from __future__ import annotations

from film_shot_agent.adapters import thirtythree
from film_shot_agent.services import chat as service


def _row(**overrides):
    row = {
        "content": '<span class="highlight">Life was like a box of chocolates</span>.',
        "startTime": "00:03:41,023",
        "endTime": "00:03:44,754",
        "startMilsec": 221023,
        "endMilsec": 224754,
        "zhContent": "人生就像一盒各式各样的巧克力",
        "lastSubtitle": {
            "content": "My mama always said",
            "zhContent": "我妈妈常说",
        },
        "nextSubtitle": {
            "content": "You never know what you're going to get.",
            "zhContent": "你永远不知道下一块将会是哪种",
        },
        "videoId": 914,
        "id": 3019118,
        "video": {
            "id": 914,
            "title": "阿甘正传 Forrest Gump",
            "zhName": "阿甘正传",
            "releaseDate": "1994-06-23(洛杉矶首映)",
            "cover": "https://oss.agilestudio.cn/ssv/202008048EsSOZOG.jpg",
            "doubanStar": 9.5,
            "subjectId": "1292720",
        },
    }
    row.update(overrides)
    return row


def test_signature_matches_the_public_client():
    params = {"_platform": "web", "_versioin": "0.2.5", "_ts": "1793322341128"}
    # Recorded from app.33tc.net: same query params produce the same signature.
    assert thirtythree._signature(params) == "1843948380d33ba931670dbf33804b76"


def test_parse_item_keeps_timecode_translation_poster_and_rating():
    hit = thirtythree._parse_item(_row(), "life was like a box of chocolates")
    assert hit is not None
    assert hit.name == "阿甘正传"
    assert hit.original_name == "阿甘正传 Forrest Gump"
    assert hit.year == 1994
    assert hit.kind == "电影"
    assert hit.timecode == "00:03:41"
    assert hit.line == "Life was like a box of chocolates."
    assert hit.line_zh == "人生就像一盒各式各样的巧克力"
    assert hit.prev_line == "My mama always said"
    assert hit.douban == "9.5"
    assert hit.douban_url == "https://movie.douban.com/subject/1292720/"
    assert hit.poster.startswith("https://oss.agilestudio.cn/")
    assert "subtitleKeyword=" in hit.source_url
    assert "langType=0" in hit.source_url
    assert hit.lang_type == 0
    assert hit.coverage == 1.0


def test_parse_item_rejects_unrelated_subtitles():
    row = _row(content="Completely different line.", zhContent="完全不同的台词")
    assert thirtythree._parse_item(row, "life was like a box of chocolates") is None


def test_parse_item_accepts_chinese_quote_split_across_lines():
    row = _row(
        content="hope is a good thing,",
        zhContent="“希望是美好的，”",
        nextSubtitle={"content": "maybe the best of things", "zhContent": "也许是人间至善"},
    )
    hit = thirtythree._parse_item(row, "希望是美好的，也许是人间至善")
    assert hit is not None
    assert hit.coverage >= 0.8


def test_search_lines_ranks_exact_matches_and_dedupes(monkeypatch):
    thirtythree.clear_cache()
    rows = [
        _row(id=1, content="Life is a box of chocolates, Forrest.", zhContent="人生就像一盒巧克力"),
        _row(id=2, content="Life was like a box of chocolates.", zhContent="人生就像一盒各式各样的巧克力"),
        _row(id=2, content="Life was like a box of chocolates.", zhContent="人生就像一盒各式各样的巧克力"),
    ]

    def fake_request(keyword, limit, client, lang_type=0):
        assert keyword == "life was like a box of chocolates"
        return rows if lang_type == 0 else []

    monkeypatch.setattr(thirtythree, "_request", fake_request)
    hits = thirtythree.search_lines("life was like a box of chocolates", limit=5)
    assert len(hits) == 2
    assert hits[0].subtitle_id == 2
    assert hits[0].coverage == 1.0


def test_chinese_index_links_to_lang_type_1():
    row = _row(
        content="说好的一辈子，差一年一个月一天一个时辰，都不算一辈子",
        zhContent="",
        lastSubtitle={},
        nextSubtitle={},
    )
    hit = thirtythree._parse_item(row, "说好的一辈子，差一年一个月一天一个时辰，都不算一辈子", 1)
    assert hit is not None
    assert hit.lang_type == 1
    assert "langType=1" in hit.source_url


def test_longest_run_rejects_a_short_shared_phrase():
    query = "希望是美好的，也许是人间至善"
    wrong = "以及至善至美的可能性"
    right = "“希望是美好的，” 也许是 ..."
    assert thirtythree._match_strength(query, wrong) < 4
    assert thirtythree._match_strength(query, right) >= 5


def test_more_subtitles_parses_the_public_window(monkeypatch):
    thirtythree.clear_cache()
    rows = [
        {
            "id": 1,
            "content": "My mama always said",
            "zhContent": "我妈妈常说",
            "startTime": "00:03:39,020",
            "endTime": "00:03:40,954",
            "startMilsec": 219020,
            "endMilsec": 220954,
        },
        {
            "id": 2,
            "content": "Life was like a box of chocolates.",
            "zhContent": "人生就像一盒各式各样的巧克力",
            "startTime": "00:03:41,023",
            "endTime": "00:03:44,754",
            "startMilsec": 221023,
            "endMilsec": 224754,
        },
    ]

    def fake_get(path, params, client):
        assert path == "/video/get-more-subtitle"
        assert params == {"subtitleId": 2}
        return rows

    monkeypatch.setattr(thirtythree, "_signed_get", fake_get)
    items = thirtythree.more_subtitles(2)
    assert len(items) == 2
    assert items[1]["start_time"] == "00:03:41"
    assert items[1]["content_zh"] == "人生就像一盒各式各样的巧克力"


def test_more_subtitles_rejects_bad_id():
    assert thirtythree.more_subtitles(0) == []
    assert thirtythree.more_subtitles(-1) == []


def test_search_lines_returns_empty_on_empty_query():
    assert thirtythree.search_lines("   ") == []


def test_extract_quote_handles_chinese_and_english_questions():
    assert service._extract_quote("“希望是美好的，也许是人间至善”出自哪部电影？") == "希望是美好的，也许是人间至善"
    assert service._extract_quote("这句台词“我看过你们人类……”是哪部片的？") == "我看过你们人类……"
    assert service._extract_quote("I am gonna make him an offer he cannot refuse — which movie is this from?") == "I am gonna make him an offer he cannot refuse"
    assert service._extract_quote("最近有什么好看的科幻片？") == ""


def test_subtitle_facts_fill_timecode_poster_and_rating():
    settings = service.get_settings().model_copy(update={"subtitle_search": True})
    ctx = service.ResearchContext(
        settings=settings,
        llm=None,  # not used by this helper
        search=lambda query, limit=6: [],
    )
    ctx.subtitle_hits = [
        {
            "name": "阿甘正传",
            "original_name": "阿甘正传 Forrest Gump",
            "year": 1994,
            "kind": "电影",
            "timecode": "00:03:41",
            "line": "Life was like a box of chocolates.",
            "line_zh": "人生就像一盒各式各样的巧克力",
            "prev_line": "My mama always said",
            "next_line": "You never know what you're going to get.",
            "poster": "https://oss.agilestudio.cn/ssv/202008048EsSOZOG.jpg",
            "douban": "9.5",
            "douban_url": "https://movie.douban.com/subject/1292720/",
            "source_url": "https://app.33tc.net/?subtitleKeyword=test",
            "coverage": 1.0,
        }
    ]
    payload = {
        "titles": [
            {
                "name": "阿甘正传",
                "year": None,
                "kind": "",
                "confidence": "medium",
                "poster": "",
                "ratings": [],
                "reviews": [],
                "watch": [],
                "scene": {"quote": "人生就像一盒巧克力", "timecode": ""},
                "evidence": [],
            }
        ],
        "citations": [],
        "caveats": [],
    }
    service._apply_subtitle_facts(payload, ctx, "“人生就像一盒巧克力”出自哪部电影？")
    title = payload["titles"][0]
    assert title["scene"]["timecode"] == "00:03:41"
    assert title["scene"]["line"] == "Life was like a box of chocolates."
    assert title["scene"]["source_url"].startswith("https://app.33tc.net/")
    assert title["poster"].startswith("https://oss.agilestudio.cn/")
    assert title["ratings"][0]["source"] == "豆瓣"
    assert title["ratings"][0]["score"] == "9.5"
    assert any("33 台词" in caveat for caveat in payload["caveats"])
