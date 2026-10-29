"""Rule-first natural language agent.

The model is deliberately not in the loop: an interview demo must behave the same way every
time it runs. Rules turn the sentence into filters and tool calls, and the returned trace
shows exactly which tool ran on which arguments — that trace is the point.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from film_shot_agent.domain.models import Title
from film_shot_agent.services.lines import LineHit, search_lines
from film_shot_agent.services.search import ShotFilters, query_shots, shot_payload

COLOR_TEMP = {
    "warm": ("暖", "暖色", "暖调", "橘", "橙", "warm", "amber", "sunset"),
    "cool": ("冷", "冷色", "冷调", "蓝", "青", "cool", "blue", "cyan", "teal"),
    "mono": ("黑白", "单色", "无彩", "mono", "monochrome"),
}
BRIGHTNESS = {
    "dark": ("暗", "压暗", "低调", "黑", "dark", "low key", "moody"),
    "bright": ("亮", "明亮", "高调", "过曝", "bright", "high key"),
}
CONTRAST = {
    "high": ("高对比", "硬光", "强反差", "high contrast"),
    "low": ("低对比", "柔光", "灰", "low contrast"),
}
SATURATION = {
    "muted": ("低饱和", "寡淡", "褪色", "muted", "desaturated"),
    "vivid": ("高饱和", "鲜艳", "浓", "vivid", "saturated"),
}
LENGTH = {
    "long": ("长镜头", "长镜", "长", "long take"),
    "short": ("快切", "短镜", "short"),
}
ASPECT = {"2.39": ("宽银幕", "宽画幅", "宽屏", "anamorphic", "2.39")}
LOOK_WORDS = ("镜头", "画面", "构图", "色调", "配色", "取景", "shot", "frame", "look")
LINE_WORDS = ("台词", "那句", "说了什么", "怎么说", "对白", "原话", "quote", "line", "dialogue")
QUOTE = re.compile(r"[「『\"“']([^」』\"”']{2,40})[」』\"”']")
STOPWORDS = (
    "找一下", "帮我找", "帮我", "我想", "想要", "看看", "有没有", "那种", "那种的",
    "台词", "那句", "对白", "原话", "说了什么", "怎么说", "镜头", "画面", "构图", "镜头里",
    "里面", "里的", "这部片里", "的那", "的是", "一个", "一部", "一下",
)
PARTICLES = "里说的了吗呢吧啊是要在和跟与及"


@dataclass
class ToolCall:
    tool: str
    args: dict
    count: int
    ms: int

    def payload(self) -> dict:
        return {"tool": self.tool, "args": self.args, "count": self.count, "ms": self.ms}


@dataclass
class AgentReply:
    answer: str
    intent: str
    filters: ShotFilters
    shots: list[dict] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)
    trace: list[ToolCall] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)

    def payload(self) -> dict:
        return {
            "answer": self.answer,
            "intent": self.intent,
            "path": self.filters.path(),
            "shots": self.shots,
            "lines": self.lines,
            "trace": [call.payload() for call in self.trace],
            "followups": self.followups,
        }


def _match(text: str, table: dict[str, tuple[str, ...]]) -> str | None:
    lowered = text.lower()
    for value, words in table.items():
        if any(word.lower() in lowered for word in words):
            return value
    return None


def extract_filters(text: str, titles: list[Title]) -> ShotFilters:
    lowered = text.lower()
    filters = ShotFilters(
        color_temp=_match(text, COLOR_TEMP),
        brightness=_match(text, BRIGHTNESS),
        contrast=_match(text, CONTRAST),
        saturation=_match(text, SATURATION),
        length=_match(text, LENGTH),
        aspect=_match(text, ASPECT),
        limit=18,
    )
    for title in titles:
        names = [title.slug, title.name.lower(), (title.name_zh or "").lower()]
        if any(name and name in lowered for name in names):
            filters = ShotFilters(**{**filters.__dict__, "title": title.slug, "limit": 18})
            break
    return filters


LOOK_KEYS = ("color_temp", "brightness", "contrast", "saturation", "length", "aspect")


def extract_keyword(text: str, titles: list[Title]) -> str:
    """Pull the search term out of a free sentence: strip titles, intent words and particles."""
    cleaned = text
    for title in titles:
        for name in (title.name, title.name_zh or "", title.slug):
            if name:
                cleaned = cleaned.replace(name, " ")
    for word in STOPWORDS:
        cleaned = cleaned.replace(word, " ")
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]+", cleaned)
    if tokens:
        return " ".join(tokens[:3])
    cjk = "".join(
        ch for ch in cleaned if "\u4e00" <= ch <= "\u9fff" and ch not in PARTICLES
    )
    return cjk.strip()[:20]


def describe(filters: ShotFilters, titles: list[Title]) -> str:
    parts = []
    if filters.title:
        title = next((t for t in titles if t.slug == filters.title), None)
        if title:
            parts.append(title.name_zh or title.name)
    for key, label in (
        ("color_temp", {"warm": "暖调", "cool": "冷调", "mono": "黑白"}),
        ("brightness", {"dark": "暗调", "bright": "亮调"}),
        ("contrast", {"high": "高对比", "low": "低对比"}),
        ("saturation", {"muted": "低饱和", "vivid": "高饱和"}),
        ("length", {"long": "长镜头", "short": "短镜头"}),
    ):
        value = getattr(filters, key)
        if value and value in label:
            parts.append(label[value])
    return " · ".join(parts)


def answer(session: Session, text: str, *, limit: int = 18) -> AgentReply:
    titles = list(session.scalars(select(Title)))
    filters = extract_filters(text, titles)
    wants_lines = any(word in text.lower() for word in LINE_WORDS)
    quote = QUOTE.search(text)
    keyword = quote.group(1) if quote else extract_keyword(text, titles)
    has_look = any(getattr(filters, key) for key in LOOK_KEYS)
    if wants_lines or quote:
        intent = "mixed" if has_look else "line"
    else:
        intent = "shot"

    reply = AgentReply(answer="", intent=intent, filters=filters)

    if intent in {"line", "mixed"}:
        started = time.perf_counter()
        hits: list[LineHit] = search_lines(
            session, keyword, limit=12, title_slug=filters.title
        )
        reply.trace.append(
            ToolCall(
                tool="search_lines",
                args={"q": keyword, "title": filters.title},
                count=len(hits),
                ms=int((time.perf_counter() - started) * 1000),
            )
        )
        from film_shot_agent.services.lines import pipeline

        reply.lines = [pipeline(session, hit) for hit in hits]

    if intent in {"shot", "mixed"}:
        started = time.perf_counter()
        shots, total = query_shots(session, filters)
        reply.trace.append(
            ToolCall(
                tool="search_shots",
                args={**filters.active, "limit": filters.limit},
                count=total,
                ms=int((time.perf_counter() - started) * 1000),
            )
        )
        reply.shots = [
            shot_payload(shot, session.get(Title, shot.title_id)) for shot in shots[:limit]
        ]
    else:
        total = 0

    described = describe(filters, titles)
    if intent == "line":
        reply.answer = (
            f"台词里找到 {len(reply.lines)} 条匹配"
            + (f"（关键词「{keyword}」）" if keyword else "")
            + "，每条都带前后句，方便判断语境。"
        )
    elif intent == "shot":
        reply.answer = (
            f"按「{described}」筛出 {total} 个镜头。"
            if described
            else f"库里共 {total} 个镜头，先给你看默认排序。"
        )
    else:
        reply.answer = f"「{described}」下筛出 {total} 个镜头，另外台词匹配 {len(reply.lines)} 条。"

    reply.followups = _followups(filters)
    return reply


def _followups(filters: ShotFilters) -> list[str]:
    suggestions = []
    if filters.color_temp == "warm":
        suggestions.append("再冷一点")
    elif filters.color_temp == "cool":
        suggestions.append("换成暖调")
    if filters.brightness != "dark":
        suggestions.append("只要暗调")
    if filters.title is None:
        suggestions.append("只在这部片里找")
    suggestions.append("把结果做成参考板")
    return suggestions[:3]
