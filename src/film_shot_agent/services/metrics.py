"""Product counters. Aggregated only: never stores query text, titles or user identity."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from film_shot_agent.domain.models import MetricEvent

KINDS = (
    "agent_message",
    "search_shots",
    "search_lines",
    "shot_opened",
    "clip_played",
    "clip_exported",
    "deck_created",
)


def bump(session: Session, kind: str) -> None:
    if kind not in KINDS:
        return
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    row = session.scalar(
        select(MetricEvent).where(MetricEvent.day == day, MetricEvent.kind == kind)
    )
    if row is None:
        session.add(MetricEvent(day=day, kind=kind, count=1))
    else:
        row.count += 1


def snapshot(session: Session) -> dict[str, int]:
    totals = {kind: 0 for kind in KINDS}
    for row in session.scalars(select(MetricEvent)):
        totals[row.kind] = totals.get(row.kind, 0) + row.count
    return totals
