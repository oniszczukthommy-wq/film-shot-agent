"""Offline fixtures: a seeded SQLite database, no ffmpeg, no network."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="film-shot-agent-"))
os.environ["FILM_AGENT_DATABASE_URL"] = f"sqlite:///{TMP / 'test.sqlite3'}"
os.environ["FILM_AGENT_LIBRARY_DIR"] = str(TMP)

from film_shot_agent.core import db  # noqa: E402
from film_shot_agent.core.config import get_settings  # noqa: E402
from film_shot_agent.domain.models import Cue, Shot, Title  # noqa: E402

get_settings.cache_clear()
db.reset_for_tests()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    db.init_db()
    seed()
    yield


def seed() -> None:
    with db.session_scope() as session:
        if session.query(Title).count():
            return
        alpha = Title(
            id="t-alpha",
            slug="alpha",
            name="Alpha",
            name_zh="阿尔法",
            year=2012,
            director="A",
            license="CC BY 3.0",
            attribution="CC BY 3.0 demo",
            source_file="/tmp/alpha.mp4",
            duration_ms=600_000,
            width=1280,
            height=534,
        )
        beta = Title(
            id="t-beta",
            slug="beta",
            name="Beta",
            name_zh="贝塔",
            year=2016,
            director="B",
            license="CC BY 3.0",
            attribution="CC BY 3.0 demo",
            source_file="/tmp/beta.mp4",
            duration_ms=300_000,
            width=1920,
            height=1080,
        )
        session.add_all([alpha, beta])
        session.flush()

        palettes = {
            "cool": [{"hex": "#1b2a4a", "weight": 0.62}, {"hex": "#3a6ea5", "weight": 0.2}],
            "warm": [{"hex": "#8a5a2b", "weight": 0.55}, {"hex": "#e0a060", "weight": 0.25}],
            "mono": [{"hex": "#1a1a1a", "weight": 0.8}, {"hex": "#dddddd", "weight": 0.1}],
        }
        for index in range(30):
            tone = ("cool", "warm", "mono")[index % 3]
            session.add(
                Shot(
                    id=f"alpha-{index:03d}",
                    title_id=alpha.id,
                    seq=index,
                    start_ms=index * 10_000,
                    end_ms=index * 10_000 + 6000,
                    thumb=f"alpha-{index:03d}.jpg",
                    frame_width=480,
                    frame_height=200,
                    aspect_ratio=2.397,
                    aspect_bucket="2.39",
                    resolution_bucket="720p",
                    length_bucket="medium" if index % 2 else "long",
                    brightness=0.2 + 0.02 * index,
                    contrast=0.3 + 0.01 * index,
                    saturation=0.1 + 0.01 * index,
                    brightness_bucket="dark" if index < 15 else "bright",
                    contrast_bucket="mid",
                    saturation_bucket="muted" if index % 2 else "vivid",
                    color_temp=tone,
                    dominant_hex=palettes[tone][0]["hex"],
                    palette_json=json.dumps(palettes[tone]),
                )
            )
        session.add(
            Shot(
                id="beta-000",
                title_id=beta.id,
                seq=0,
                start_ms=0,
                end_ms=4000,
                thumb="beta-000.jpg",
                frame_width=480,
                frame_height=270,
                aspect_ratio=1.78,
                aspect_bucket="1.78",
                resolution_bucket="1080p",
                length_bucket="medium",
                brightness=0.7,
                contrast=0.5,
                saturation=0.6,
                brightness_bucket="bright",
                contrast_bucket="high",
                saturation_bucket="vivid",
                color_temp="warm",
                dominant_hex="#8a5a2b",
                palette_json=json.dumps(palettes["warm"]),
            )
        )

        lines = [
            "You have your robotics.",
            "I just want to be awesome in space.",
            "Why don't you admit you're freaked out by my robot hand?",
            "We have to follow our passions.",
        ]
        for index, text in enumerate(lines):
            session.add(
                Cue(
                    id=f"alpha-cue-{index:03d}",
                    title_id=alpha.id,
                    seq=index,
                    start_ms=20_000 + index * 3000,
                    end_ms=22_000 + index * 3000,
                    text=text,
                    text_zh="机器人" if "robot" in text else None,
                )
            )


@pytest.fixture()
def session():
    with db.session_scope() as active:
        yield active
