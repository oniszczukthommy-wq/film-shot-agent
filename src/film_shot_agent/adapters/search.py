"""Web search adapter.

One interface, three providers. The free DuckDuckGo HTML endpoint is the default so the
project runs before anyone buys a search API key; Tavily / Brave take over when a key is
present. Everything returned here is untrusted input: URLs are normalised, private hosts
are rejected, and callers may only cite what this module actually returned.
"""

from __future__ import annotations

import html
import ipaddress
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from threading import Lock
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

import httpx

from film_shot_agent.core.config import Settings, get_settings

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TRACKING_KEYS = {"fbclid", "gclid", "spm", "from", "source", "ref", "referrer"}
MAX_SNIPPET = 420
CACHE_MAX = 256


class SearchError(RuntimeError):
    """Search could not be completed. Message is safe to show to the user."""


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    provider: str = ""

    def payload(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "provider": self.provider,
        }


_cache: dict[tuple[str, str, int], tuple[float, list[SearchHit]]] = {}
_cache_lock = Lock()
_ddg_blocked_until = 0.0


def clear_cache() -> None:
    global _ddg_blocked_until
    with _cache_lock:
        _cache.clear()
    _ddg_blocked_until = 0.0


def active_provider(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    configured = (settings.search_provider or "auto").strip().lower()
    has_key = bool(settings.search_api_key.strip())
    if configured in {"tavily", "brave"}:
        return configured if has_key else "duckduckgo"
    if configured != "auto":
        return "duckduckgo"
    if settings.search_api_key.strip():
        # A key alone cannot tell us which vendor; default to Tavily and let the error say so.
        return "tavily"
    return "duckduckgo"


def web_search(
    query: str,
    *,
    limit: int = 6,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> list[SearchHit]:
    settings = settings or get_settings()
    query = " ".join(str(query or "").split())[:300]
    if not query:
        return []
    limit = max(1, min(10, int(limit)))
    provider = active_provider(settings)
    cache_key = (provider, query, limit)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < settings.research_cache_ttl:
            return list(cached[1])

    hits = _dispatch(provider, query, limit, settings, client)
    cleaned = _dedupe([hit for hit in hits if safe_http_url(hit.url)])
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[cache_key] = (now, cleaned)
    return list(cleaned)


def _dispatch(
    provider: str,
    query: str,
    limit: int,
    settings: Settings,
    client: httpx.Client | None,
) -> list[SearchHit]:
    try:
        if provider == "tavily":
            return _tavily(query, limit, settings, client)
        if provider == "brave":
            return _brave(query, limit, settings, client)
        return _free_search(query, limit, client)
    except SearchError:
        if provider == "duckduckgo":
            raise
        # A paid provider failing should not take the whole answer down.
        return _free_search(query, limit, client)


def _free_search(query: str, limit: int, client: httpx.Client | None) -> list[SearchHit]:
    """Free chain: DuckDuckGo HTML, then 360 for Chinese coverage.

    DuckDuckGo answers 202 with an empty shell when it rate-limits a home IP. Falling
    through keeps the product usable without a search key, and the provider is recorded
    on every hit so the UI never pretends the source is something else.
    """
    global _ddg_blocked_until
    hits: list[SearchHit] = []
    if time.monotonic() >= _ddg_blocked_until:
        try:
            hits = _duckduckgo(query, limit, client)
        except SearchError:
            hits = []
        if hits:
            return hits
        # Rate-limited or empty: stop paying the 10-20s tax on every later query.
        _ddg_blocked_until = time.monotonic() + 600
    try:
        hits = _so360(query, limit, client)
    except SearchError:
        hits = []
    if hits:
        return hits
    raise SearchError("联网搜索暂时不可用，请稍后再试。")


def _tavily(
    query: str, limit: int, settings: Settings, client: httpx.Client | None
) -> list[SearchHit]:
    if not settings.search_api_key.strip():
        raise SearchError("未配置搜索 API Key。")
    try:
        response = _client(client).post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.search_api_key.strip(),
                "query": query,
                "max_results": limit,
                "search_depth": "basic",
                "include_answer": False,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SearchError("Tavily 搜索失败。") from exc
    hits = []
    for row in data.get("results", [])[:limit]:
        hits.append(
            SearchHit(
                title=_clean_text(row.get("title", "")),
                url=normalize_url(str(row.get("url", ""))),
                snippet=_clean_text(row.get("content", ""), MAX_SNIPPET),
                provider="tavily",
            )
        )
    return hits


def _brave(
    query: str, limit: int, settings: Settings, client: httpx.Client | None
) -> list[SearchHit]:
    if not settings.search_api_key.strip():
        raise SearchError("未配置搜索 API Key。")
    try:
        response = _client(client).get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit, "safesearch": "moderate"},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": settings.search_api_key.strip(),
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SearchError("Brave 搜索失败。") from exc
    hits = []
    for row in (data.get("web", {}) or {}).get("results", [])[:limit]:
        hits.append(
            SearchHit(
                title=_clean_text(row.get("title", "")),
                url=normalize_url(str(row.get("url", ""))),
                snippet=_clean_text(row.get("description", ""), MAX_SNIPPET),
                provider="brave",
            )
        )
    return hits


def _duckduckgo(query: str, limit: int, client: httpx.Client | None) -> list[SearchHit]:
    try:
        response = _client(client).get(
            "https://html.duckduckgo.com/html/",
            params={"q": query, "kl": "cn-zh"},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"},
            timeout=12.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SearchError("DuckDuckGo 搜索失败，请稍后再试。") from exc
    return parse_duckduckgo(response.text, limit=limit)


def _so360(query: str, limit: int, client: httpx.Client | None) -> list[SearchHit]:
    try:
        response = _client(client).get(
            "https://www.so.com/s",
            params={"q": query, "ie": "utf-8"},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=15.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SearchError("360 搜索失败。") from exc
    return parse_so360(response.text, limit=limit)


def parse_so360(page: str, *, limit: int = 6) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for block in re.findall(r'<li class="res-list".*?</li>', page, re.S):
        if len(hits) >= limit:
            break
        url_match = re.search(r'data-mdurl="([^"]+)"', block)
        title_match = re.search(r"<h3[^>]*>(.*?)</h3>", block, re.S)
        if not url_match or not title_match:
            continue
        snippet_match = re.search(
            r'<span[^>]*data-result-summary[^>]*>(.*?)</span>', block, re.S
        ) or re.search(r'<p class="res-desc">(.*?)</p>', block, re.S)
        url = normalize_url(html.unescape(url_match.group(1)))
        title = _clean_text(title_match.group(1))
        snippet = _clean_text(snippet_match.group(1), MAX_SNIPPET) if snippet_match else ""
        if title and safe_http_url(url):
            hits.append(
                SearchHit(title=title, url=url, snippet=snippet, provider="so360")
            )
    return hits


def _client(client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(follow_redirects=True)


class _DuckParser(HTMLParser):
    """Pair each `result__a` anchor with the next `result__snippet` block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: list[tuple[str, str]] = []
        self.snippets: list[str] = []
        self._mode: str | None = None
        self._depth = 0
        self._target_tag = ""
        self._buf: list[str] = []
        self._href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: (value or "") for key, value in attrs}
        classes = values.get("class", "")
        if self._mode is None:
            if tag == "a" and "result__a" in classes:
                self._start("title", tag, values.get("href", ""))
            elif "result__snippet" in classes:
                self._start("snippet", tag, "")
            return
        if tag == self._target_tag or tag in {"b", "strong", "em", "span", "div", "a"}:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._mode is None:
            return
        if self._depth > 1:
            self._depth -= 1
            return
        if self._mode == "title" and tag == "a":
            self.titles.append((self._href, _clean_text("".join(self._buf))))
            self._reset()
        elif self._mode == "snippet" and tag == self._target_tag:
            self.snippets.append(_clean_text("".join(self._buf), MAX_SNIPPET))
            self._reset()

    def handle_data(self, data: str) -> None:
        if self._mode:
            self._buf.append(data)

    def _start(self, mode: str, tag: str, href: str) -> None:
        self._mode = mode
        self._target_tag = tag
        self._depth = 1
        self._buf = []
        self._href = href

    def _reset(self) -> None:
        self._mode = None
        self._depth = 0
        self._target_tag = ""
        self._buf = []
        self._href = ""


def parse_duckduckgo(page: str, *, limit: int = 6) -> list[SearchHit]:
    parser = _DuckParser()
    try:
        parser.feed(page)
    except Exception:  # noqa: BLE001 - malformed third-party HTML must not 500
        return []
    hits: list[SearchHit] = []
    for index, (href, title) in enumerate(parser.titles):
        if len(hits) >= limit:
            break
        url = normalize_url(_unwrap_duckduckgo(href))
        if not title or not safe_http_url(url):
            continue
        snippet = parser.snippets[index] if index < len(parser.snippets) else ""
        hits.append(SearchHit(title=title, url=url, snippet=snippet, provider="duckduckgo"))
    return hits


def _unwrap_duckduckgo(href: str) -> str:
    href = html.unescape((href or "").strip())
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = "https://duckduckgo.com" + href
    parsed = urlparse(href)
    host = (parsed.hostname or "").lower()
    if host.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return normalize_url(target)
    return normalize_url(href)


def normalize_url(url: str) -> str:
    """Drop fragments and tracking params; keep the rest of the query verbatim."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
    ]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            parsed.params,
            urlencode(pairs),
            "",
        )
    )


def safe_http_url(url: str) -> bool:
    if not url or len(url) > 600:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().strip(".")
    if host in {"localhost", "0.0.0.0"} or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    )


def _clean_text(value: object, limit: int = 260) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _dedupe(hits: list[SearchHit]) -> list[SearchHit]:
    seen: set[str] = set()
    out: list[SearchHit] = []
    for hit in hits:
        if hit.url in seen:
            continue
        seen.add(hit.url)
        out.append(hit)
    return out
