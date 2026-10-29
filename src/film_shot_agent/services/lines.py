"""Line search with surrounding context and highlight spans.

The reference product's core reading experience: every hit is a line, but you decide
whether it means anything by the two lines around it. So a search never returns a bare
string — it returns the line plus its neighbours and the exact match offsets.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from film_shot_agent.domain.models import Cue, Title

TOKEN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


@dataclass(frozen=True)
class LineHit:
    id: str
    title_slug: str
    title: str
    seq: int
    start_ms: int
    end_ms: int
    text: str
    text_zh: str | None
    prev: tuple[str, str | None] | None
    next: tuple[str, str | None] | None
    spans: tuple[tuple[int, int], ...]
    score: float


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def highlight_spans(text: str, query: str) -> tuple[tuple[int, int], ...]:
    """Case-insensitive spans for the whole phrase, then for individual tokens."""
    if not query.strip():
        return ()
    lowered = text.casefold()
    spans: list[tuple[int, int]] = []
    start = lowered.find(query.casefold())
    while start != -1:
        spans.append((start, start + len(query)))
        start = lowered.find(query.casefold(), start + len(query))
    if spans:
        return tuple(_merge(spans))
    for token in TOKEN.findall(query.casefold()):
        if len(token) < 2:
            continue
        start = lowered.find(token)
        while start != -1:
            spans.append((start, start + len(token)))
            start = lowered.find(token, start + len(token))
    return tuple(_merge(spans))


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def search_lines(
    session: Session, query: str, *, limit: int = 20, title_slug: str | None = None
) -> list[LineHit]:
    query = query.strip()
    if not query:
        return []
    stmt = select(Cue, Title).join(Title, Cue.title_id == Title.id)
    if title_slug:
        stmt = stmt.where(Title.slug == title_slug)
    needle = normalize(query)
    tokens = [normalize(token) for token in TOKEN.findall(query) if len(token) > 1]

    scored: list[tuple[float, Cue, Title]] = []
    for cue, title in session.execute(stmt).all():
        haystack = normalize(f"{cue.text} {cue.text_zh or ''}")
        score = 0.0
        if needle and needle in haystack:
            score = 3.0 + min(1.0, len(needle) / max(1, len(haystack)))
        elif tokens and all(token in haystack for token in tokens):
            score = 2.0
        elif tokens and any(token in haystack for token in tokens):
            score = 1.0 * sum(1 for token in tokens if token in haystack) / len(tokens)
        if score:
            scored.append((score, cue, title))

    scored.sort(key=lambda row: (-row[0], row[2].slug, row[1].seq))
    hits = []
    for score, cue, title in scored[:limit]:
        hits.append(
            LineHit(
                id=cue.id,
                title_slug=title.slug,
                title=title.name_zh or title.name,
                seq=cue.seq,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                text=cue.text,
                text_zh=cue.text_zh,
                prev=_neighbour(session, cue, -1),
                next=_neighbour(session, cue, 1),
                spans=highlight_spans(cue.text, query) + highlight_spans(cue.text_zh or "", query),
                score=round(score, 3),
            )
        )
    return hits


def _neighbour(session: Session, cue: Cue, step: int) -> tuple[str, str | None] | None:
    row = session.scalar(
        select(Cue).where(Cue.title_id == cue.title_id, Cue.seq == cue.seq + step)
    )
    if row is None:
        return None
    return (row.text, row.text_zh)


def line_payload(hit: LineHit) -> dict:
    return {
        "id": hit.id,
        "title_slug": hit.title_slug,
        "title": hit.title,
        "seq": hit.seq,
        "start_ms": hit.start_ms,
        "end_ms": hit.end_ms,
        "timestamp": format_timecode(hit.start_ms),
        "text": hit.text,
        "text_zh": hit.text_zh,
        "prev": hit.prev[0] if hit.prev else None,
        "prev_zh": hit.prev[1] if hit.prev else None,
        "next": hit.next[0] if hit.next else None,
        "next_zh": hit.next[1] if hit.next else None,
        "spans": [list(span) for span in hit.spans],
        "score": hit.score,
    }


def shot_at(session: Session, title_id: str, at_ms: int):
    """The shot covering `at_ms`, falling back to the next one when a line lands in a gap."""
    from film_shot_agent.domain.models import Shot as ShotModel

    shot = session.scalar(
        select(ShotModel)
        .where(
            ShotModel.title_id == title_id,
            ShotModel.start_ms <= at_ms,
            ShotModel.end_ms > at_ms,
        )
        .limit(1)
    )
    if shot is not None:
        return shot
    return session.scalar(
        select(ShotModel)
        .where(ShotModel.title_id == title_id, ShotModel.start_ms >= at_ms)
        .order_by(ShotModel.start_ms)
        .limit(1)
    )


def pipeline(session: Session, hit: LineHit) -> dict:
    """One line plus the shot that is on screen while it is spoken."""
    payload = line_payload(hit)
    from film_shot_agent.domain.models import Title as TitleModel

    title = session.scalar(select(TitleModel).where(TitleModel.slug == hit.title_slug))
    shot = shot_at(session, title.id, hit.start_ms) if title is not None else None
    if shot is not None:
        payload["shot_id"] = shot.id
        payload["shot_thumb"] = shot.thumb
        payload["shot_start_ms"] = shot.start_ms
        payload["shot_palette"] = shot.palette_json
    return payload


def format_timecode(ms: int) -> str:
    seconds, millis = divmod(max(0, ms), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
