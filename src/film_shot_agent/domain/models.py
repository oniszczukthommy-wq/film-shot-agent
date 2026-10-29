"""Content and interaction models for the shot library."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from film_shot_agent.core.db import Base


def _uuid() -> str:
    return str(uuid4())


class Title(Base):
    __tablename__ = "titles"
    __table_args__ = (UniqueConstraint("slug", name="uq_titles_slug"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_zh: Mapped[str | None] = mapped_column(String(200))
    year: Mapped[int | None] = mapped_column(Integer)
    director: Mapped[str | None] = mapped_column(String(200))
    license: Mapped[str] = mapped_column(String(120), nullable=False, default="CC BY 3.0")
    attribution: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_file: Mapped[str] = mapped_column(String(400), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    shots: Mapped[list["Shot"]] = relationship(back_populates="title", cascade="all, delete")
    cues: Mapped[list["Cue"]] = relationship(back_populates="title", cascade="all, delete")


class Shot(Base):
    """One camera shot: a representative frame plus machine-computed look attributes."""

    __tablename__ = "shots"
    __table_args__ = (
        Index("ix_shots_title_seq", "title_id", "seq"),
        Index("ix_shots_look", "color_temp", "brightness_bucket"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    thumb: Mapped[str] = mapped_column(String(200), nullable=False)
    frame_width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frame_height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    aspect_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=1.78)
    aspect_bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="1.78")
    resolution_bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="720p")
    length_bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")

    brightness: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    contrast: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    saturation: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    brightness_bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="mid")
    contrast_bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="mid")
    saturation_bucket: Mapped[str] = mapped_column(String(16), nullable=False, default="mid")
    color_temp: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")

    dominant_hex: Mapped[str] = mapped_column(String(7), nullable=False, default="#808080")
    # JSON: [{"hex": "#rrggbb", "weight": 0.42}, ...] ordered by area
    palette_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    title: Mapped[Title] = relationship(back_populates="shots")


class Cue(Base):
    """One subtitle line, with its neighbours resolvable by seq."""

    __tablename__ = "cues"
    __table_args__ = (Index("ix_cues_title_seq", "title_id", "seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_zh: Mapped[str | None] = mapped_column(Text)

    title: Mapped[Title] = relationship(back_populates="cues")


class Deck(Base):
    __tablename__ = "decks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    items: Mapped[list["DeckItem"]] = relationship(
        back_populates="deck", cascade="all, delete", order_by="DeckItem.position"
    )


class DeckItem(Base):
    __tablename__ = "deck_items"
    __table_args__ = (Index("ix_deck_items_deck", "deck_id", "position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    deck_id: Mapped[str] = mapped_column(ForeignKey("decks.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # shot | cue
    ref_id: Mapped[str] = mapped_column(String(36), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    caption: Mapped[str | None] = mapped_column(String(300))

    deck: Mapped[Deck] = relationship(back_populates="items")


class MetricEvent(Base):
    """Aggregated product counters. Never stores query text or titles."""

    __tablename__ = "metric_events"
    __table_args__ = (UniqueConstraint("day", "kind", name="uq_metric_day_kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
