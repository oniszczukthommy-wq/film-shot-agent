"""Build the demo library: shots, look attributes and subtitle lines.

Usage:
    uv run python scripts/ingest.py            # index everything in data/library/raw
    uv run python scripts/ingest.py --reset    # drop existing rows first
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pysubs2
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from film_shot_agent.adapters import ffmpeg  # noqa: E402
from film_shot_agent.core.config import get_settings  # noqa: E402
from film_shot_agent.core.db import init_db, session_scope  # noqa: E402
from film_shot_agent.domain.models import Cue, Deck, DeckItem, MetricEvent, Shot, Title  # noqa: E402
from film_shot_agent.services.look import analyze  # noqa: E402


@dataclass(frozen=True)
class FilmSpec:
    slug: str
    name: str
    name_zh: str
    year: int
    director: str
    file: str
    subtitles: tuple[tuple[str, str], ...] = ()  # (language, path)


FILMS = (
    FilmSpec(
        slug="tears-of-steel",
        name="Tears of Steel",
        name_zh="钢铁之泪",
        year=2012,
        director="Ian Hubert",
        file="toes_720p.mov",
        subtitles=(("en", "subs/TOS-en.srt"), ("zh", "subs/TOS-CH.srt")),
    ),
    FilmSpec(
        slug="big-buck-bunny",
        name="Big Buck Bunny",
        name_zh="大雄兔",
        year=2008,
        director="Sacha Goedegebure",
        file="bbb_sunflower_1080p_30fps_normal.mp4",
    ),
)

ATTRIBUTION = (
    "© Blender Foundation | www.blender.org — 以 CC BY 3.0 授权，允许在署名前提下复制、"
    "分发与改编，包括商业用途。"
)


def build_web_copy(path: Path, spec: FilmSpec) -> Path:
    """Produce a browser-streamable MP4 once; playback reads this instead of the master file."""
    target = get_settings().library_dir / "web" / f"{spec.slug}.mp4"
    if target.exists() and target.stat().st_size > 0:
        return target
    ffmpeg.remux_for_web(path, target)
    return target


def build_shots(path: Path, spec: FilmSpec) -> int:
    settings = get_settings()
    info = ffmpeg.probe(path)
    aspect = ffmpeg.detect_aspect(path) or round(info.width / info.height, 3)
    cuts = ffmpeg.scene_cuts(path, settings.scene_threshold)
    bounds = [0.0, *cuts]
    # Merge neighbouring shots when the count exceeds the cap so ingest stays bounded.
    limit = settings.max_shots_per_title
    if len(bounds) > limit:
        step = len(bounds) / limit
        bounds = [bounds[int(i * step)] for i in range(limit)]
    bounds.append(info.duration_ms / 1000)

    thumbs = settings.library_dir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)

    with session_scope() as session:
        title = session.scalar(select(Title).where(Title.slug == spec.slug))
        if title is None:
            title = Title(
                slug=spec.slug,
                name=spec.name,
                name_zh=spec.name_zh,
                year=spec.year,
                director=spec.director,
                license="CC BY 3.0",
                attribution=ATTRIBUTION,
                source_file=str(path),
                duration_ms=info.duration_ms,
                width=info.width,
                height=info.height,
            )
            session.add(title)
            session.flush()
        else:
            title.duration_ms = info.duration_ms
            title.width = info.width
            title.height = info.height
            session.execute(delete(Shot).where(Shot.title_id == title.id))

        made = 0
        for index in range(len(bounds) - 1):
            start_ms = int(bounds[index] * 1000)
            end_ms = int(bounds[index + 1] * 1000)
            if end_ms - start_ms < 400:
                end_ms = start_ms + 400
            sample = (start_ms + min(600, (end_ms - start_ms) // 3)) / 1000
            shot_id = f"{spec.slug}-{index:04d}"
            thumb_name = f"{shot_id}.jpg"
            ffmpeg.extract_frame(path, sample, thumbs / thumb_name, settings.shot_thumb_width)
            look = analyze(ffmpeg.raw_rgb(path, sample), 64, 36)
            length = (end_ms - start_ms) / 1000
            session.add(
                Shot(
                    id=shot_id,
                    title_id=title.id,
                    seq=index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    thumb=thumb_name,
                    frame_width=settings.shot_thumb_width,
                    frame_height=int(settings.shot_thumb_width / aspect),
                    aspect_ratio=aspect,
                    aspect_bucket=_aspect_bucket(aspect),
                    resolution_bucket="1080p" if info.height >= 1000 else "720p",
                    length_bucket="short" if length < 2.5 else "medium" if length < 6 else "long",
                    brightness=look.brightness,
                    contrast=look.contrast,
                    saturation=look.saturation,
                    brightness_bucket="mid",
                    contrast_bucket="mid",
                    saturation_bucket="mid",
                    color_temp=look.color_temp,
                    dominant_hex=look.dominant_hex,
                    palette_json=json.dumps(
                        [{"hex": s.hex, "weight": s.weight} for s in look.palette],
                        ensure_ascii=False,
                    ),
                )
            )
            made += 1
        return made


def build_cues(spec: FilmSpec) -> int:
    root = get_settings().library_dir
    paths = {language: root / rel for language, rel in spec.subtitles}
    if not paths.get("en"):
        return 0
    primary = _load_srt(paths["en"])
    secondary = _load_srt(paths["zh"]) if paths.get("zh") else []

    with session_scope() as session:
        title = session.scalar(select(Title).where(Title.slug == spec.slug))
        if title is None:
            return 0
        session.execute(delete(Cue).where(Cue.title_id == title.id))
        for index, (start, end, text) in enumerate(primary):
            session.add(
                Cue(
                    id=f"{spec.slug}-cue-{index:04d}",
                    title_id=title.id,
                    seq=index,
                    start_ms=start,
                    end_ms=end,
                    text=text,
                    text_zh=_nearest(secondary, start),
                )
            )
    return len(primary)


def _load_srt(path: Path) -> list[tuple[int, int, str]]:
    if not path.exists():
        return []
    parsed = pysubs2.load(str(path), encoding="utf-8")
    rows = []
    for event in parsed:
        text = event.plaintext.strip().replace("\n", " ")
        if text:
            rows.append((event.start, event.end, text))
    return sorted(rows)


def _nearest(rows: list[tuple[int, int, str]], start_ms: int) -> str | None:
    if not rows:
        return None
    best = min(rows, key=lambda row: abs(row[0] - start_ms))
    return best[2] if abs(best[0] - start_ms) <= 2500 else None


def _aspect_bucket(value: float) -> str:
    for label, ratio in (
        ("1.33", 1.33), ("1.66", 1.66), ("1.78", 1.78),
        ("1.85", 1.85), ("2.00", 2.00), ("2.39", 2.39),
    ):
        if abs(value - ratio) < 0.06:
            return label
    return "other"


def recalibrate_buckets() -> None:
    """Bucket look attributes by library quantiles so every facet stays informative."""
    with session_scope() as session:
        shots = list(session.scalars(select(Shot)))
        if len(shots) < 6:
            return
        for field, buckets in (
            ("brightness", ("dark", "mid", "bright")),
            ("contrast", ("low", "mid", "high")),
            ("saturation", ("muted", "mid", "vivid")),
        ):
            values = sorted(getattr(shot, field) for shot in shots)
            low = values[len(values) // 3]
            high = values[(len(values) * 2) // 3]
            target = f"{field}_bucket"
            for shot in shots:
                value = getattr(shot, field)
                index = 0 if value < low else 1 if value < high else 2
                setattr(shot, target, buckets[index])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--only", default="")
    args = parser.parse_args()

    init_db()
    if args.reset:
        with session_scope() as session:
            for model in (DeckItem, Deck, MetricEvent, Cue, Shot, Title):
                session.execute(delete(model))

    root = get_settings().library_dir / "raw"
    for spec in FILMS:
        if args.only and args.only != spec.slug:
            continue
        path = root / spec.file
        if not path.exists():
            print(f"跳过 {spec.slug}：缺少 {path}")
            continue
        build_web_copy(path, spec)
        shots = build_shots(path, spec)
        cues = build_cues(spec)
        print(f"{spec.name}: {shots} 个镜头, {cues} 条台词")
    recalibrate_buckets()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
