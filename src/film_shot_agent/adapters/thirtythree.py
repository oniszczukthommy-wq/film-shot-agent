"""Best-effort adapter for the public 33台词 (33tc) subtitle search.

Why this exists
---------------
Web search can confirm a famous quote, but it rarely knows the timestamp and it can
mis-attribute a line. 33台词 indexes subtitle files, so one query returns the film,
the exact timecode, the original line, the Chinese translation and the poster.

This is an *unofficial* endpoint used by app.33tc.net. It is used one short quote at
a time for personal research only: no bulk crawling, no local subtitle corpus, and no
video URLs are exposed. Any failure returns an empty list so callers can fall back to
web search. Results are cached in memory for a few minutes to avoid repeat requests.
"""

from __future__ import annotations

import hashlib
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from urllib.parse import quote as urlquote
from urllib.parse import urlencode

import httpx

API_URL = "https://33-api.agilestudio.cn/api/v2/search"
APP_URL = "https://app.33tc.net/"
CLIENT_VERSION = "0.2.5"
REQUEST_TIMEOUT = 8.0
CACHE_TTL = 600.0
CACHE_MAX = 128
MIN_COVERAGE = 0.58

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9']+")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


class SubtitleError(RuntimeError):
    """The subtitle search failed. The message is safe to show to the user."""


@dataclass(frozen=True)
class SubtitleHit:
    name: str
    original_name: str
    year: int | None
    kind: str
    timecode: str
    start_ms: int
    end_ms: int
    line: str
    line_zh: str
    prev_line: str
    prev_zh: str
    next_line: str
    next_zh: str
    poster: str
    douban: str
    douban_url: str
    source_url: str
    video_id: int | None
    subtitle_id: int | None
    query: str
    lang_type: int
    coverage: float
    strength: int

    def payload(self) -> dict:
        return {
            "name": self.name,
            "original_name": self.original_name,
            "year": self.year,
            "kind": self.kind,
            "timecode": self.timecode,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "line": self.line,
            "line_zh": self.line_zh,
            "prev_line": self.prev_line,
            "prev_zh": self.prev_zh,
            "next_line": self.next_line,
            "next_zh": self.next_zh,
            "poster": self.poster,
            "douban": self.douban,
            "douban_url": self.douban_url,
            "source_url": self.source_url,
            "video_id": self.video_id,
            "subtitle_id": self.subtitle_id,
            "query": self.query,
            "lang_type": self.lang_type,
            "coverage": round(self.coverage, 2),
            "strength": self.strength,
        }


_cache: dict[tuple[str, int], tuple[float, list[SubtitleHit]]] = {}
_context_cache: dict[int, tuple[float, list[dict]]] = {}
_cache_lock = Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
        _context_cache.clear()


def _signature(params: dict[str, str]) -> str:
    raw = ",".join(f"{key}={params[key]}" for key in sorted(params)) + ","
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _clean(value: object, limit: int = 400) -> str:
    text = html.unescape(_TAG_RE.sub("", str(value or "")))
    return _WS_RE.sub(" ", text).strip()[:limit]


def _timecode(value: object) -> str:
    raw = str(value or "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})", raw)
    return f"{match.group(1)}:{match.group(2)}:{match.group(3)}" if match else ""


def _year(value: object) -> int | None:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _kind(video: dict) -> str:
    title = str(video.get("title") or "")
    if re.search(r"第[一二三四五六七八九十\d]+季|第\d+集|Season\s*\d+|S\d{1,2}E\d+", title, re.I):
        return "剧集"
    if video.get("videoType") in {1, 2}:
        return "剧集"
    return "电影"


def _poster(value: object) -> str:
    url = str(value or "").strip()
    if url.startswith("https://oss.agilestudio.cn/"):
        return url[:400]
    return ""


def _douban(video: dict) -> tuple[str, str]:
    raw = video.get("doubanStar")
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return "", ""
    if not 0 < score <= 10:
        return "", ""
    subject = str(video.get("subjectId") or "").strip()
    url = f"https://movie.douban.com/subject/{subject}/" if subject.isdigit() else ""
    return f"{score:.1f}", url


def _source_url(keyword: str, lang_type: int) -> str:
    query = urlencode(
        {"subtitleKeyword": keyword, "langType": lang_type, "phraseMode": 0},
        quote_via=urlquote,
    )
    return f"{APP_URL}?{query}"


def phrase_coverage(keyword: str, hit_text: str) -> float:
    """How much of the quote actually appears in the returned subtitle window.

    Chinese matching is character based because word segmentation is unreliable for a
    short quote; English uses whole words so "a" does not match every sentence.
    """

    query = _WS_RE.sub(" ", keyword.casefold()).strip()
    haystack = _WS_RE.sub(" ", hit_text.casefold()).strip()
    if not query or not haystack:
        return 0.0
    if _HAN_RE.search(query):
        want = {char for char in query if _HAN_RE.match(char)}
        if not want:
            return 0.0
        return len(want & set(haystack)) / len(want)
    words = {word for word in _WORD_RE.findall(query) if len(word) > 1}
    if not words:
        return 0.0
    return len(words & set(_WORD_RE.findall(haystack))) / len(words)


def _match_strength(keyword: str, hit_text: str) -> int:
    """Longest contiguous run of the quote found in the subtitle window.

    33台词 is keyword based, so a short shared phrase ("至善") can pull in an unrelated
    film. A contiguous run is a much better guard than set overlap: the right quote
    shares a long phrase, the wrong one shares one or two characters.
    """

    query = _WS_RE.sub(" ", keyword.casefold()).strip()
    haystack = _WS_RE.sub(" ", hit_text.casefold()).strip()
    if not query or not haystack:
        return 0
    if _HAN_RE.search(query):
        chars = [char for char in query if _HAN_RE.match(char)]
        best = 0
        for start in range(len(chars)):
            for end in range(len(chars), start + best, -1):
                if "".join(chars[start:end]) in haystack:
                    best = end - start
                    break
        return best
    words = _WORD_RE.findall(query)
    best = 0
    for start in range(len(words)):
        for end in range(len(words), start + best, -1):
            if " ".join(words[start:end]) in haystack:
                best = end - start
                break
    return best


def _parse_item(item: dict, keyword: str, lang_type: int = 0) -> SubtitleHit | None:
    video = item.get("video") or {}
    line = _clean(item.get("content"))
    line_zh = _clean(item.get("zhContent"))
    prev_item = item.get("lastSubtitle") or {}
    next_item = item.get("nextSubtitle") or {}
    prev_line = _clean(prev_item.get("content"))
    prev_zh = _clean(prev_item.get("zhContent"))
    next_line = _clean(next_item.get("content"))
    next_zh = _clean(next_item.get("zhContent"))
    if not line and not line_zh:
        return None
    full_title = _clean(video.get("title"), 200)
    zh_name = _clean(video.get("zhName"), 120)
    name = zh_name or full_title
    if not name:
        return None
    haystack = " ".join([line, line_zh, prev_line, prev_zh, next_line, next_zh])
    coverage = phrase_coverage(keyword, haystack)
    strength = _match_strength(keyword, haystack)
    if coverage < MIN_COVERAGE:
        return None
    # A long contiguous run keeps split subtitles; a short shared phrase is noise.
    if strength < 4:
        return None
    timecode = _timecode(item.get("startTime"))
    douban, douban_url = _douban(video)
    original_name = full_title if full_title and full_title != name else ""
    return SubtitleHit(
        name=name,
        original_name=original_name,
        year=_year(video.get("releaseDate")),
        kind=_kind(video),
        timecode=timecode,
        start_ms=int(item.get("startMilsec") or 0),
        end_ms=int(item.get("endMilsec") or 0),
        line=line,
        line_zh=line_zh,
        prev_line=prev_line,
        prev_zh=prev_zh,
        next_line=next_line,
        next_zh=next_zh,
        poster=_poster(video.get("cover")),
        douban=douban,
        douban_url=douban_url,
        source_url=_source_url(keyword, lang_type),
        video_id=item.get("videoId") if isinstance(item.get("videoId"), int) else None,
        subtitle_id=item.get("id") if isinstance(item.get("id"), int) else None,
        query=keyword,
        lang_type=lang_type,
        coverage=coverage,
        strength=strength,
    )


def _rank(hits: list[SubtitleHit]) -> list[SubtitleHit]:
    # Exact subtitle matches first, then higher coverage, then better-known films.
    return sorted(
        hits,
        key=lambda hit: (
            -hit.coverage,
            0 if hit.timecode else 1,
            -(float(hit.douban) if hit.douban else 0.0),
            hit.start_ms,
        ),
    )


def _request(keyword: str, limit: int, client: httpx.Client, lang_type: int = 0) -> list[dict]:
    stamp = str(int(time.time() * 1000) - 9999)
    params = {"_platform": "web", "_versioin": CLIENT_VERSION, "_ts": stamp}
    body = {
        "subtitleKeyword": keyword,
        "langType": lang_type,
        "addAiSubFlag": 0,
        "exactFlag": 0,
        "phraseMode": 0,
        "indexType": 0,
        "page": 1,
        "limit": max(10, min(limit, 50)),
    }
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=utf-8",
        "X-Signature": _signature(params),
        "Origin": APP_URL.rstrip("/"),
        "Referer": APP_URL,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    }
    try:
        response = client.post(
            API_URL,
            params=params,
            json=body,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SubtitleError("字幕库暂时不可用。") from exc
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise SubtitleError("字幕库返回了异常结果。")
    data = payload.get("data") or {}
    rows = data.get("list")
    return rows if isinstance(rows, list) else []


def _signed_get(path: str, params: dict, client: httpx.Client) -> object:
    stamp = str(int(time.time() * 1000) - 9999)
    query = {"_platform": "web", "_versioin": CLIENT_VERSION, "_ts": stamp}
    query.update({key: str(value) for key, value in params.items()})
    headers = {
        "Accept": "application/json, text/plain, */*",
        "X-Signature": _signature(query),
        "Origin": APP_URL.rstrip("/"),
        "Referer": APP_URL,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    }
    try:
        response = client.get(
            f"https://33-api.agilestudio.cn/api{path}",
            params=query,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SubtitleError("字幕库暂时不可用。") from exc
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise SubtitleError("字幕库返回了异常结果。")
    data = payload.get("data")
    return data if isinstance(data, (dict, list)) else {}


def _parse_context(row: dict) -> dict | None:
    if not isinstance(row, dict):
        return None
    content = _clean(row.get("content"))
    content_zh = _clean(row.get("zhContent"))
    if not content and not content_zh:
        return None
    return {
        "id": row.get("id") if isinstance(row.get("id"), int) else None,
        "start_time": _timecode(row.get("startTime")),
        "end_time": _timecode(row.get("endTime")),
        "start_ms": int(row.get("startMilsec") or 0),
        "end_ms": int(row.get("endMilsec") or 0),
        "content": content,
        "content_zh": content_zh,
    }


def more_subtitles(
    subtitle_id: int,
    *,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Return the subtitle window around one line (33台词's 「更多字幕」)."""

    if not isinstance(subtitle_id, int) or subtitle_id <= 0:
        return []
    now = time.monotonic()
    with _cache_lock:
        cached = _context_cache.get(subtitle_id)
        if cached and now - cached[0] < CACHE_TTL:
            return list(cached[1])
    own_client = client is None
    http_client = client or httpx.Client(follow_redirects=True)
    try:
        data = _signed_get("/video/get-more-subtitle", {"subtitleId": subtitle_id}, http_client)
    finally:
        if own_client:
            http_client.close()
    rows = data.get("list") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        rows = []
    items = [item for item in (_parse_context(row) for row in rows) if item]
    with _cache_lock:
        if len(_context_cache) >= CACHE_MAX:
            _context_cache.pop(next(iter(_context_cache)))
        _context_cache[subtitle_id] = (now, items)
    return items


def search_lines(
    keyword: str,
    *,
    limit: int = 6,
    client: httpx.Client | None = None,
) -> list[SubtitleHit]:
    """Search one quote in the 33台词 subtitle index.

    Returns [] rather than raising when the query is empty or nothing matches. A
    network failure raises SubtitleError so the caller can record a caveat; callers
    that do not care can simply catch it and fall back to web search.
    """

    keyword = _WS_RE.sub(" ", str(keyword or "")).strip()[:120]
    if not keyword:
        return []
    cache_key = (keyword.casefold(), limit)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL:
            return list(cached[1])

    own_client = client is None
    http_client = client or httpx.Client(follow_redirects=True)
    rows_by_lang: dict[int, list[dict]] = {}
    failures = 0

    def fetch(lang_type: int) -> tuple[int, list[dict]]:
        nonlocal failures
        try:
            return lang_type, _request(keyword, limit, http_client, lang_type)
        except SubtitleError:
            failures += 1
            return lang_type, []

    try:
        # langType 0 is the English/Western subtitle index; 1 is the Chinese one.
        # A Chinese quote often exists only in the Chinese index (e.g. 霸王别姬).
        with ThreadPoolExecutor(max_workers=2) as pool:
            for lang_type, rows in pool.map(fetch, (0, 1)):
                rows_by_lang[lang_type] = rows
    finally:
        if own_client:
            http_client.close()
    if failures == 2:
        raise SubtitleError("字幕库暂时不可用。")

    parsed = [
        hit
        for lang_type, rows in rows_by_lang.items()
        for hit in (
            _parse_item(row, keyword, lang_type) for row in rows if isinstance(row, dict)
        )
        if hit
    ]
    # One card per film/timecode; the API can return the same line more than once.
    seen: set[tuple[str, str, str]] = set()
    unique: list[SubtitleHit] = []
    for hit in _rank(parsed):
        key = (hit.name.casefold(), hit.timecode, hit.line.casefold())
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
        if len(unique) >= limit:
            break

    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[cache_key] = (now, unique)
    return unique
