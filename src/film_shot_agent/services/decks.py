"""Reference decks: ordered boards of shots and lines."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from film_shot_agent.domain.models import Cue, Deck, DeckItem, Shot, Title
from film_shot_agent.services.lines import format_timecode
from film_shot_agent.services.search import shot_payload

KINDS = {"shot", "cue"}


class DeckError(ValueError):
    pass


def create_deck(session: Session, name: str) -> Deck:
    name = name.strip()[:120] or "未命名参考板"
    deck = Deck(name=name)
    session.add(deck)
    session.flush()
    return deck


def list_decks(session: Session) -> list[dict]:
    rows = session.execute(
        select(Deck).order_by(Deck.created_at.desc())
    ).scalars()
    return [
        {
            "id": deck.id,
            "name": deck.name,
            "count": session.scalar(
                select(func.count()).select_from(DeckItem).where(DeckItem.deck_id == deck.id)
            ),
            "created_at": deck.created_at.isoformat(),
        }
        for deck in rows
    ]


def add_item(
    session: Session, deck_id: str, kind: str, ref_id: str, caption: str | None = None
) -> DeckItem:
    if kind not in KINDS:
        raise DeckError("只支持 shot 或 cue。")
    deck = session.get(Deck, deck_id)
    if deck is None:
        raise DeckError("参考板不存在。")
    if kind == "shot" and session.get(Shot, ref_id) is None:
        raise DeckError("镜头不存在。")
    if kind == "cue" and session.get(Cue, ref_id) is None:
        raise DeckError("台词不存在。")
    existing = session.scalar(
        select(DeckItem).where(
            DeckItem.deck_id == deck_id, DeckItem.kind == kind, DeckItem.ref_id == ref_id
        )
    )
    if existing:
        return existing
    position = session.scalar(
        select(func.coalesce(func.max(DeckItem.position), -1)).where(DeckItem.deck_id == deck_id)
    )
    item = DeckItem(
        deck_id=deck_id, kind=kind, ref_id=ref_id, position=(position or 0) + 1, caption=caption
    )
    session.add(item)
    session.flush()
    return item


def remove_item(session: Session, deck_id: str, item_id: str) -> None:
    session.execute(
        delete(DeckItem).where(DeckItem.deck_id == deck_id, DeckItem.id == item_id)
    )


def delete_deck(session: Session, deck_id: str) -> None:
    session.execute(delete(DeckItem).where(DeckItem.deck_id == deck_id))
    session.execute(delete(Deck).where(Deck.id == deck_id))


def deck_payload(session: Session, deck_id: str) -> dict:
    deck = session.get(Deck, deck_id)
    if deck is None:
        raise DeckError("参考板不存在。")
    items = list(
        session.scalars(
            select(DeckItem).where(DeckItem.deck_id == deck_id).order_by(DeckItem.position)
        )
    )
    rendered = []
    for item in items:
        base = {"id": item.id, "kind": item.kind, "caption": item.caption}
        if item.kind == "shot":
            shot = session.get(Shot, item.ref_id)
            if shot is None:
                continue
            base["shot"] = shot_payload(shot, session.get(Title, shot.title_id))
        else:
            cue = session.get(Cue, item.ref_id)
            if cue is None:
                continue
            title = session.get(Title, cue.title_id)
            base["line"] = {
                "id": cue.id,
                "text": cue.text,
                "text_zh": cue.text_zh,
                "timestamp": format_timecode(cue.start_ms),
                "title": (title.name_zh or title.name) if title else None,
                "title_slug": title.slug if title else None,
            }
        rendered.append(base)
    return {"id": deck.id, "name": deck.name, "items": rendered}
