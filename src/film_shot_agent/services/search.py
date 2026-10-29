"""Shot filtering, faceted counts and the path-encoded query language.

Query state lives in the URL as `/browse/<key>/<value>/<key>/<value>/…`, mirroring the
shareable-URL model used by the reference sites: any search can be pasted back and replayed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Literal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from film_shot_agent.domain.models import Shot, Title
from film_shot_agent.services.look import color_distance, hex_to_rgb

DIMENSIONS: tuple[str, ...] = (
    "title",
    "color_temp",
    "brightness",
    "contrast",
    "saturation",
    "aspect",
    "resolution",
    "length",
)

FACET_LABELS: dict[str, str] = {
    "title": "影片",
    "color_temp": "色调",
    "brightness": "亮度",
    "contrast": "对比度",
    "saturation": "饱和度",
    "aspect": "画幅",
    "resolution": "分辨率",
    "length": "镜头长度",
    "shade": "取色",
}

COLOR_TEMP_LABELS = {
    "warm": "暖调",
    "cool": "冷调",
    "mixed": "冷暖混合",
    "neutral": "中性",
    "mono": "黑白/低彩",
}
BRIGHTNESS_LABELS = {"dark": "暗调", "mid": "中间调", "bright": "亮调"}
CONTRAST_LABELS = {"low": "低对比", "mid": "中对比", "high": "高对比"}
SATURATION_LABELS = {"muted": "低饱和", "mid": "常规", "vivid": "高饱和"}
LENGTH_LABELS = {"short": "短(<2.5s)", "medium": "中(2.5-6s)", "long": "长(>6s)"}

_FIELD = {
    "color_temp": "color_temp",
    "brightness": "brightness_bucket",
    "contrast": "contrast_bucket",
    "saturation": "saturation_bucket",
    "aspect": "aspect_bucket",
    "resolution": "resolution_bucket",
    "length": "length_bucket",
}

SORTS = {
    "relevance": "默认",
    "time": "时间顺序",
    "bright": "由亮到暗",
    "dark": "由暗到亮",
    "long": "镜头最长",
}


@dataclass(frozen=True)
class ShotFilters:
    title: str | None = None
    color_temp: str | None = None
    brightness: str | None = None
    contrast: str | None = None
    saturation: str | None = None
    aspect: str | None = None
    resolution: str | None = None
    length: str | None = None
    shade: str | None = None
    distance: int = 8
    proportion: int = 3
    sort: str = "relevance"
    limit: int = 36
    offset: int = 0
    extras: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def active(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in DIMENSIONS if getattr(self, key)}

    def with_value(self, key: str, value: str | None) -> ShotFilters:
        return replace(self, **{key: value}, offset=0)

    def path(self, *, include_sort: bool = True) -> str:
        parts: list[str] = []
        for key in DIMENSIONS:
            value = getattr(self, key)
            if value:
                parts += [key, value]
        if self.shade:
            parts += ["shade", f"{self.shade}~{self.distance}~{self.proportion}"]
        if include_sort and self.sort != "relevance":
            parts += ["sort", self.sort]
        return "/" + "/".join(parts) if parts else "/"


def parse_filters(segments: list[str]) -> ShotFilters:
    """`["color_temp","warm","aspect","2.39"]` → filters."""
    values: dict[str, str] = {}
    pairs = [segments[i : i + 2] for i in range(0, len(segments) - 1, 2)]
    for key, value in pairs:
        if key in DIMENSIONS or key in {"shade", "sort", "distance", "proportion"}:
            values[key] = value

    shade = values.get("shade")
    distance, proportion = 8, 3
    if shade and "~" in shade:
        shade, _, rest = shade.partition("~")
        numbers = (rest.split("~") + ["", ""])[:2]
        distance = _clamp_int(numbers[0], 8, 0, 40)
        proportion = _clamp_int(numbers[1], 3, 0, 60)
    return ShotFilters(
        title=values.get("title"),
        color_temp=values.get("color_temp"),
        brightness=values.get("brightness"),
        contrast=values.get("contrast"),
        saturation=values.get("saturation"),
        aspect=values.get("aspect"),
        resolution=values.get("resolution"),
        length=values.get("length"),
        shade=shade.lstrip("#") if shade else None,
        distance=distance,
        proportion=proportion,
        sort=values.get("sort", "relevance"),
    )


def _clamp_int(raw: str, fallback: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(float(raw))))
    except (TypeError, ValueError):
        return fallback


def _apply(stmt: Select, filters: ShotFilters, *, skip: str | None = None) -> Select:
    if filters.title and skip != "title":
        stmt = stmt.where(Title.slug == filters.title)
    for key, column in _FIELD.items():
        value = getattr(filters, key)
        if value and skip != key:
            stmt = stmt.where(getattr(Shot, column) == value)
    return stmt


def query_shots(session: Session, filters: ShotFilters) -> tuple[list[Shot], int]:
    stmt = select(Shot).join(Title, Shot.title_id == Title.id)
    stmt = _apply(stmt, filters)
    rows = [shot for shot in session.scalars(stmt.order_by(Shot.title_id, Shot.seq))]

    if filters.shade:
        rows = [shot for shot in rows if _matches_shade(shot, filters)]

    rows.sort(key=_sort_key(filters.sort))
    total = len(rows)
    return rows[filters.offset : filters.offset + filters.limit], total


def _sort_key(mode: str):
    if mode == "bright":
        return lambda shot: (-shot.brightness, shot.seq)
    if mode == "dark":
        return lambda shot: (shot.brightness, shot.seq)
    if mode == "long":
        return lambda shot: (-(shot.end_ms - shot.start_ms), shot.seq)
    if mode == "time":
        return lambda shot: (shot.title_id, shot.seq)
    return lambda shot: (shot.title_id, shot.seq)


def _matches_shade(shot: Shot, filters: ShotFilters) -> bool:
    target = hex_to_rgb(filters.shade or "000000")
    for swatch in json.loads(shot.palette_json or "[]"):
        if swatch["weight"] * 100 < filters.proportion:
            continue
        if color_distance(hex_to_rgb(swatch["hex"].lstrip("#")), target) <= filters.distance:
            return True
    return False


def facet_counts(session: Session, filters: ShotFilters) -> dict[str, list[dict]]:
    """For each dimension, count values as if that dimension were not filtered."""
    facets: dict[str, list[dict]] = {}
    shade_ids: set[str] | None = None
    if filters.shade:
        # Colour matching happens on the palette JSON, so narrow the facet universe first.
        shade_ids = {
            shot.id for shot in session.scalars(select(Shot)) if _matches_shade(shot, filters)
        }
        if not shade_ids:
            return {key: [] for key in DIMENSIONS}
    for key in DIMENSIONS:
        if key == "title":
            counted = func.count(Shot.id)
            stmt = (
                _apply(
                    select(Title.slug, Title.name_zh, Title.name, counted),
                    filters,
                    skip="title",
                )
                .join(Title, Shot.title_id == Title.id)
                .group_by(Title.slug, Title.name_zh, Title.name)
            )
            if shade_ids is not None:
                stmt = stmt.where(Shot.id.in_(shade_ids))
            rows = session.execute(stmt).all()
            facets[key] = [
                {
                    "value": slug,
                    "label": name_zh or name,
                    "count": count,
                    "selected": filters.title == slug,
                }
                for slug, name_zh, name, count in sorted(rows, key=lambda row: -row[3])
            ]
            continue
        column = getattr(Shot, _FIELD[key])
        stmt = (
            _apply(select(column, func.count(Shot.id)), filters, skip=key)
            .join(Title, Shot.title_id == Title.id)
            .group_by(column)
        )
        if shade_ids is not None:
            stmt = stmt.where(Shot.id.in_(shade_ids))
        rows = session.execute(stmt).all()
        labels = _labels_for(key)
        facets[key] = [
            {
                "value": value,
                "label": labels.get(value, value),
                "count": count,
                "selected": getattr(filters, key) == value,
            }
            for value, count in sorted(rows, key=lambda row: -row[1])
            if value
        ]
    return facets


def _labels_for(key: str) -> dict[str, str]:
    return {
        "color_temp": COLOR_TEMP_LABELS,
        "brightness": BRIGHTNESS_LABELS,
        "contrast": CONTRAST_LABELS,
        "saturation": SATURATION_LABELS,
        "length": LENGTH_LABELS,
    }.get(key, {})


def shot_payload(shot: Shot, title: Title | None = None) -> dict:
    return {
        "id": shot.id,
        "seq": shot.seq,
        "title_slug": title.slug if title else None,
        "title": (title.name_zh or title.name) if title else None,
        "title_en": title.name if title else None,
        "year": title.year if title else None,
        "start_ms": shot.start_ms,
        "end_ms": shot.end_ms,
        "duration_ms": shot.end_ms - shot.start_ms,
        "thumb": shot.thumb,
        "aspect_ratio": shot.aspect_ratio,
        "aspect_bucket": shot.aspect_bucket,
        "resolution": shot.resolution_bucket,
        "look": {
            "palette": json.loads(shot.palette_json or "[]"),
            "dominant_hex": shot.dominant_hex,
            "brightness": shot.brightness,
            "contrast": shot.contrast,
            "saturation": shot.saturation,
            "color_temp": shot.color_temp,
            "color_temp_label": COLOR_TEMP_LABELS.get(shot.color_temp, shot.color_temp),
            "brightness_bucket": shot.brightness_bucket,
            "contrast_bucket": shot.contrast_bucket,
            "saturation_bucket": shot.saturation_bucket,
            "length_bucket": shot.length_bucket,
        },
    }


SortMode = Literal["relevance", "time", "bright", "dark", "long"]
