"""Deck export: a contact-sheet PNG (ffmpeg) and a print-ready HTML view."""

from __future__ import annotations

import shutil
import tempfile
from html import escape
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from film_shot_agent.adapters import ffmpeg
from film_shot_agent.core.config import get_settings
from film_shot_agent.domain.models import Cue, Deck, DeckItem, Shot, Title
from film_shot_agent.services.decks import DeckError, deck_payload
from film_shot_agent.services.lines import format_timecode, shot_at


def collage(session: Session, deck_id: str, *, columns: int = 3, tile_width: int = 520) -> Path:
    """Compose every shot in the deck into one grid image."""
    deck = session.get(Deck, deck_id)
    if deck is None:
        raise DeckError("参考板不存在。")
    shots = _deck_shots(session, deck_id)
    if not shots:
        raise DeckError("参考板里还没有镜头，先加几个再导出。")
    columns = max(1, min(columns, 4))
    rows = (len(shots) + columns - 1) // columns

    library = get_settings().library_dir
    out_dir = library / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"deck-{deck_id[:8]}-{columns}x{rows}.jpg"

    with tempfile.TemporaryDirectory(prefix="deck-") as tmp:
        prepared = []
        for index, shot in enumerate(shots):
            target = Path(tmp) / f"{index:04d}.jpg"
            _fit(library / "thumbs" / shot.thumb, target, tile_width)
            prepared.append(target)
        code, stderr = ffmpeg.grid_images(
            prepared,
            out,
            columns=columns,
            cell_width=tile_width,
            cell_height=int(tile_width * 9 / 16),
            padding=12,
        )
    if code != 0 or not out.exists():
        raise DeckError(f"拼图生成失败：{stderr[:300]}")
    return out


def print_html(session: Session, deck_id: str) -> str:
    """A4 landscape board: image + title + timecode + caption, printable to PDF."""
    payload = deck_payload(session, deck_id)
    cells = []
    for item in payload["items"]:
        if item["kind"] == "shot" and item.get("shot"):
            shot = item["shot"]
            cells.append(
                f"""
      <figure>
        <img src="{escape('/media/thumbs/' + shot['thumb'])}" alt="">
        <figcaption>
          <b>{escape(shot['title'] or '')}</b>
          <span>{escape(shot['title_en'] or '')}{
            (' · ' + str(shot['year'])) if shot.get('year') else ''}</span>
          <em>{format_timecode(shot['start_ms'])}</em>
          {f'<p>{escape(item["caption"])}</p>' if item.get("caption") else ''}
        </figcaption>
      </figure>"""
            )
        elif item["kind"] == "cue" and item.get("line"):
            line = item["line"]
            cells.append(
                f"""
      <figure class="quote">
        <blockquote>{escape(line['text'])}</blockquote>
        {f'<p class="zh">{escape(line["text_zh"])}</p>' if line.get("text_zh") else ''}
        <figcaption>
          <b>{escape(line['title'] or '')}</b>
          <em>{escape(line['timestamp'])}</em>
        </figcaption>
      </figure>"""
            )
    titles = list(session.scalars(select(Title)))
    credit = " · ".join(sorted({title.attribution for title in titles if title.attribution}))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{escape(payload['name'])} · 参考板</title>
<style>
  @page {{ size: A4 landscape; margin: 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font: 12px/1.5 -apple-system, "PingFang SC", sans-serif; color: #111; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline;
            border-bottom: 2px solid #111; padding-bottom: 6px; margin-bottom: 14px; }}
  h1 {{ font-size: 20px; margin: 0; letter-spacing: .04em; }}
  .meta {{ color: #666; font-size: 11px; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }}
  figure {{ margin: 0; break-inside: avoid; }}
  figure img {{ width: 100%; display: block; background: #000; }}
  figcaption {{ display: flex; flex-wrap: wrap; gap: 6px; padding-top: 5px; font-size: 11px; }}
  figcaption b {{ font-weight: 600; }}
  figcaption span {{ color: #666; }}
  figcaption em {{ margin-left: auto; font-style: normal; color: #666;
                  font-variant-numeric: tabular-nums; }}
  figcaption p {{ flex-basis: 100%; margin: 2px 0 0; color: #333; }}
  figure.quote {{ border: 1px solid #ddd; padding: 12px; min-height: 150px;
                  display: flex; flex-direction: column; }}
  blockquote {{ margin: 0; font-size: 15px; line-height: 1.45; }}
  .zh {{ color: #0a7f8c; margin: 6px 0 0; font-size: 12px; }}
  figure.quote figcaption {{ margin-top: auto; }}
  footer {{ margin-top: 16px; color: #888; font-size: 10px;
            border-top: 1px solid #ddd; padding-top: 6px; }}
  .print {{ position: fixed; right: 16px; bottom: 16px; padding: 10px 18px;
            border: 0; border-radius: 999px; background: #111; color: #fff;
            font-size: 13px; cursor: pointer; }}
  @media print {{ .print {{ display: none; }} }}
</style></head>
<body>
  <header>
    <h1>{escape(payload['name'])}</h1>
    <div class="meta">{len(payload['items'])} 项 · Shot Agent 参考板</div>
  </header>
  <main class="grid">{''.join(cells)}</main>
  <footer>{escape(credit)}</footer>
  <button class="print" onclick="window.print()">打印 / 另存为 PDF</button>
</body></html>"""


def _deck_shots(session: Session, deck_id: str) -> list[Shot]:
    items = list(
        session.scalars(
            select(DeckItem).where(DeckItem.deck_id == deck_id).order_by(DeckItem.position)
        )
    )
    shots: list[Shot] = []
    for item in items:
        if item.kind == "shot":
            shot = session.get(Shot, item.ref_id)
            if shot is not None:
                shots.append(shot)
        else:
            cue = session.get(Cue, item.ref_id)
            if cue is not None:
                shots.append(_shot_for_cue(session, cue))
    return [shot for shot in shots if shot is not None]


def _shot_for_cue(session: Session, cue: Cue) -> Shot | None:
    return shot_at(session, cue.title_id, cue.start_ms)


def _fit(source: Path, target: Path, width: int) -> None:
    if _is_wide_enough(source, width):
        shutil.copyfile(source, target)
    else:
        _scale(source, target, width)


def _is_wide_enough(source: Path, width: int) -> bool:
    try:
        return ffmpeg.probe(source).width >= width
    except Exception:  # noqa: BLE001 - a broken thumb should not break the export
        return False


def _scale(source: Path, target: Path, width: int) -> None:
    ffmpeg.scale_image(source, target, width)


