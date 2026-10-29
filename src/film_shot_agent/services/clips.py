"""Clip and still export. Everything is rendered from files we already own."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from film_shot_agent.adapters import ffmpeg
from film_shot_agent.core.config import get_settings
from film_shot_agent.domain.models import Shot, Title

GIF_WIDTHS = {"xs": 320, "s": 480, "m": 640, "l": 960, "xl": 1920}
MAX_CLIP_MS = 8000


class ExportError(RuntimeError):
    pass


def export_shot(session: Session, shot_id: str, fmt: str) -> tuple[Path, str]:
    """Return (path, media_type) for one shot exported as mp4 or gif-<size>."""
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise ExportError("镜头不存在。")
    title = session.get(Title, shot.title_id)
    if title is None:
        raise ExportError("镜头所属影片不存在。")
    source = Path(title.source_file)
    if not source.exists():
        raise ExportError("源文件已不在本地，无法导出。")

    fmt = fmt.lower()
    if fmt != "mp4" and fmt not in {"gif-" + key for key in GIF_WIDTHS}:
        raise ExportError("不支持的导出格式。")

    settings = get_settings()
    out_dir = settings.library_dir / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = hashlib.sha256(f"{shot.id}:{fmt}:{shot.start_ms}".encode()).hexdigest()[:12]
    suffix = "mp4" if fmt == "mp4" else "gif"
    out = out_dir / f"{shot.id}-{stamp}.{suffix}"
    if out.exists():
        return out, "video/mp4" if fmt == "mp4" else "image/gif"

    start = max(0, shot.start_ms - 400)
    end = min(shot.end_ms + 400, start + MAX_CLIP_MS)
    if fmt == "mp4":
        ffmpeg.make_clip(source, start, end, out)
        return out, "video/mp4"
    width = GIF_WIDTHS[fmt.split("-", 1)[1]]
    ffmpeg.make_gif(source, start, min(end, start + 5000), out, width)
    return out, "image/gif"


def still_path(shot: Shot) -> Path:
    return get_settings().library_dir / "thumbs" / shot.thumb
