"""TMDB lookup: ratings, reviews and legal watch providers.

TMDB is the only structured source we use for "where can I watch this". Its
`watch/providers` payload is JustWatch data split into free / ads / flatrate / rent / buy,
which is exactly the ordering the product needs: free first, never a piracy link.
"""

from __future__ import annotations

import time
from threading import Lock

import httpx

from film_shot_agent.core.config import Settings, get_settings

API = "https://api.themoviedb.org/3"
IMAGE = "https://image.tmdb.org/t/p/w300"
ACCESS_LABELS = {
    "free": "免费",
    "ads": "免费（含广告）",
    "flatrate": "会员",
    "rent": "付费租",
    "buy": "付费买",
}
ACCESS_ORDER = {"free": 0, "ads": 1, "flatrate": 2, "rent": 3, "buy": 4}
CACHE_TTL = 3600


class TMDBError(RuntimeError):
    pass


_cache: dict[tuple[str, str, int | None, str], tuple[float, dict]] = {}
_lock = Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def lookup(
    title: str,
    *,
    kind: str = "auto",
    year: int | None = None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Resolve one title and return a normalised fact sheet. Raises TMDBError."""
    settings = settings or get_settings()
    title = " ".join(str(title or "").split())[:120]
    if not settings.has_tmdb:
        raise TMDBError("TMDB 未配置。")
    if not title:
        raise TMDBError("片名不能为空。")
    kind = kind if kind in {"movie", "tv", "auto"} else "auto"
    cache_key = (kind, title.casefold(), year, settings.region)
    now = time.monotonic()
    with _lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]

    kinds = ["movie", "tv"] if kind == "auto" else [kind]
    matches: list[dict] = []
    for candidate_kind in kinds:
        matches.extend(_search(candidate_kind, title, year, settings, client))
    if not matches:
        raise TMDBError("TMDB 没有找到这部片。")
    matches.sort(key=lambda row: (row.get("popularity") or 0), reverse=True)
    best = matches[0]
    facts = _details(best["kind"], best["id"], settings, client)
    facts["alternatives"] = [
        {
            "id": row["id"],
            "kind": row["kind"],
            "name": row.get("name"),
            "year": row.get("year"),
            "url": _title_url(row["kind"], row["id"]),
        }
        for row in matches[1:4]
    ]
    with _lock:
        if len(_cache) >= 256:
            _cache.clear()
        _cache[cache_key] = (now, facts)
    return facts


def _client(client: httpx.Client | None) -> httpx.Client:
    return client or httpx.Client(follow_redirects=True)


def _get(path: str, params: dict, settings: Settings, client: httpx.Client | None) -> dict:
    merged = {**params, "api_key": settings.tmdb_api_key.strip(), "language": "zh-CN"}
    try:
        response = _client(client).get(API + path, params=merged, timeout=20.0)
    except httpx.HTTPError as exc:
        raise TMDBError("TMDB 连接失败。") from exc
    if response.status_code >= 400:
        raise TMDBError(f"TMDB 返回错误（HTTP {response.status_code}）。")
    try:
        data = response.json()
    except ValueError as exc:
        raise TMDBError("TMDB 返回了无法解析的内容。") from exc
    return data if isinstance(data, dict) else {}


def _search(
    kind: str, title: str, year: int | None, settings: Settings, client: httpx.Client | None
) -> list[dict]:
    params: dict = {"query": title, "include_adult": "false", "page": 1}
    if year:
        params["year" if kind == "movie" else "first_air_date_year"] = year
    data = _get(f"/search/{kind}", params, settings, client)
    rows = []
    for row in data.get("results", [])[:5]:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        date = row.get("release_date") or row.get("first_air_date") or ""
        rows.append(
            {
                "id": int(row["id"]),
                "kind": kind,
                "name": row.get("title") or row.get("name") or title,
                "year": int(date[:4]) if date[:4].isdigit() else None,
                "popularity": row.get("popularity") or 0,
            }
        )
    return rows


def _details(kind: str, tmdb_id: int, settings: Settings, client: httpx.Client | None) -> dict:
    data = _get(
        f"/{kind}/{tmdb_id}",
        {"append_to_response": "watch/providers,reviews"},
        settings,
        client,
    )
    date = data.get("release_date") or data.get("first_air_date") or ""
    title = data.get("title") or data.get("name") or ""
    original = data.get("original_title") or data.get("original_name") or title
    votes = int(data.get("vote_count") or 0)
    score = data.get("vote_average")
    ratings = []
    if score is not None and votes:
        ratings.append(
            {
                "source": "TMDB",
                "score": round(float(score), 1),
                "out_of": 10,
                "votes": votes,
                "url": _title_url(kind, tmdb_id),
            }
        )
    providers = _providers(data.get("watch/providers") or {}, settings.region)
    reviews = []
    for row in (data.get("reviews") or {}).get("results", [])[:3]:
        if not isinstance(row, dict):
            continue
        reviews.append(
            {
                "source": "TMDB 用户评论",
                "author": row.get("author") or "",
                "summary": " ".join(str(row.get("content") or "").split())[:360],
                "url": row.get("url") or _title_url(kind, tmdb_id),
            }
        )
    return {
        "tmdb_id": tmdb_id,
        "kind": "电影" if kind == "movie" else "剧集",
        "name": title,
        "original_name": original if original != title else "",
        "year": int(date[:4]) if date[:4].isdigit() else None,
        "overview": " ".join(str(data.get("overview") or "").split())[:500],
        "genres": [row.get("name") for row in data.get("genres", []) if row.get("name")],
        "runtime": data.get("runtime") or (data.get("episode_run_time") or [None])[0],
        "poster": (IMAGE + data["poster_path"]) if data.get("poster_path") else "",
        "ratings": ratings,
        "watch": providers,
        "reviews": reviews,
        "url": _title_url(kind, tmdb_id),
        "region": settings.region,
    }


def _providers(payload: dict, region: str) -> list[dict]:
    results = payload.get("results") or {}
    row = results.get(region) or {}
    link = row.get("link") or ""
    providers: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for access in ("free", "ads", "flatrate", "rent", "buy"):
        for item in row.get(access) or []:
            if not isinstance(item, dict):
                continue
            name = item.get("provider_name") or ""
            if not name or (name, access) in seen:
                continue
            seen.add((name, access))
            providers.append(
                {
                    "platform": name,
                    "access": access,
                    "access_label": ACCESS_LABELS[access],
                    "url": link,
                    "note": "TMDB / JustWatch 数据",
                }
            )
    providers.sort(key=lambda item: ACCESS_ORDER.get(item["access"], 9))
    return providers[:10]


def _title_url(kind: str, tmdb_id: int) -> str:
    return f"https://www.themoviedb.org/{'movie' if kind == 'movie' else 'tv'}/{tmdb_id}"
