"""Search adapter: parsing, URL hygiene, caching. No network."""

from __future__ import annotations

from film_shot_agent.adapters import search
from film_shot_agent.core.config import Settings

DDG_HTML = """
<html><body>
<div class="result results_links">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a"
       href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fmovie.douban.com%2Fsubject%2F3541415%2F%3Futm_source%3Dddg&amp;rut=x">
      盗梦空间 (豆瓣)
    </a>
  </h2>
  <a class="result__snippet" href="#">盗梦空间 Inception <b>9.4</b> 分，评分人数很多。</a>
</div>
<div class="result results_links">
  <h2 class="result__title">
    <a class="result__a" href="https://www.imdb.com/title/tt1375666/">Inception - IMDb</a>
  </h2>
  <div class="result__snippet">8.8/10 · A thief steals secrets.</div>
</div>
</body></html>
"""


def test_parse_duckduckgo_unwraps_and_pairs():
    hits = search.parse_duckduckgo(DDG_HTML, limit=5)
    assert [hit.url for hit in hits] == [
        "https://movie.douban.com/subject/3541415/",
        "https://www.imdb.com/title/tt1375666/",
    ]
    assert hits[0].title == "盗梦空间 (豆瓣)"
    assert "9.4" in hits[0].snippet
    assert "8.8/10" in hits[1].snippet


def test_normalize_url_drops_tracking_and_fragment():
    dirty = "https://example.com/a?utm_source=x&id=3&fbclid=y#top"
    assert search.normalize_url(dirty) == "https://example.com/a?id=3"


def test_safe_url_rejects_private_and_non_http():
    assert not search.safe_http_url("javascript:alert(1)")
    assert not search.safe_http_url("http://127.0.0.1/admin")
    assert not search.safe_http_url("http://192.168.1.2/")
    assert not search.safe_http_url("http://localhost:8000")
    assert not search.safe_http_url("https://user:pass@example.com/")
    assert search.safe_http_url("https://movie.douban.com/subject/1/")


def test_search_cache_hits_once(monkeypatch):
    settings = Settings(search_provider="duckduckgo", research_cache_ttl=3600)
    search.clear_cache()
    calls = []

    def fake_dispatch(provider, query, limit, settings, client):
        calls.append((provider, query, limit))
        return [search.SearchHit("t", "https://example.com/", "s", provider)]

    monkeypatch.setattr(search, "_dispatch", fake_dispatch)
    first = search.web_search("盗梦空间", settings=settings)
    second = search.web_search("盗梦空间", settings=settings)
    assert len(calls) == 1
    assert first == second

SO_HTML = """
<ul>
<li class="res-list" data-result-type="normal">
  <h3 class="res-title">
    <a href="https://www.so.com/link?m=x"
       data-mdurl="https://movie.douban.com/subject/3541415/">盗梦空间 (豆瓣)</a>
  </h3>
  <p class="res-desc"><span data-result-summary>盗梦空间 Inception 豆瓣评分 9.4</span></p>
</li>
</ul>
"""


def test_parse_so360_uses_real_url():
    hits = search.parse_so360(SO_HTML, limit=3)
    assert hits[0].url == "https://movie.douban.com/subject/3541415/"
    assert hits[0].title == "盗梦空间 (豆瓣)"
    assert "9.4" in hits[0].snippet
    assert hits[0].provider == "so360"


def test_free_search_falls_back_to_360(monkeypatch):
    def failing_ddg(query, limit, client):
        raise search.SearchError("duckduckgo down")

    monkeypatch.setattr(search, "_duckduckgo", failing_ddg)
    monkeypatch.setattr(
        search,
        "_so360",
        lambda query, limit, client: [
            search.SearchHit("t", "https://example.com/", "s", "so360")
        ],
    )
    hits = search._free_search("q", 5, None)
    assert hits[0].provider == "so360"
