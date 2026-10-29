"""HTTP surface: browse, facets, lines, decks, clips, agent."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from film_shot_agent.core.config import get_settings
from film_shot_agent.core.db import get_session
from film_shot_agent.domain.models import Cue, Shot, Title
from film_shot_agent.services import agent as agent_service
from film_shot_agent.services import clips as clip_service
from film_shot_agent.services import deck_export
from film_shot_agent.services import decks as deck_service
from film_shot_agent.services import lines as line_service
from film_shot_agent.services import metrics as metric_service
from film_shot_agent.services.search import (
    FACET_LABELS,
    SORTS,
    ShotFilters,
    facet_counts,
    parse_filters,
    query_shots,
    shot_payload,
)

router = APIRouter()


def _filters_from_query(request: Request) -> ShotFilters:
    params = request.query_params
    return ShotFilters(
        title=params.get("title") or None,
        color_temp=params.get("color_temp") or None,
        brightness=params.get("brightness") or None,
        contrast=params.get("contrast") or None,
        saturation=params.get("saturation") or None,
        aspect=params.get("aspect") or None,
        resolution=params.get("resolution") or None,
        length=params.get("length") or None,
        shade=(params.get("shade") or "").lstrip("#") or None,
        distance=int(params.get("distance") or 8),
        proportion=int(params.get("proportion") or 3),
        sort=params.get("sort") or "relevance",
        limit=min(int(params.get("limit") or 36), 120),
        offset=max(int(params.get("offset") or 0), 0),
    )


@router.get("/api/health")
def health(session: Session = Depends(get_session)) -> dict:
    return {
        "titles": session.scalar(select(func.count()).select_from(Title)),
        "shots": session.scalar(select(func.count()).select_from(Shot)),
        "lines": session.scalar(select(func.count()).select_from(Cue)),
    }


@router.get("/api/titles")
def titles(session: Session = Depends(get_session)) -> dict:
    rows = list(session.scalars(select(Title).order_by(Title.name)))
    return {
        "items": [
            {
                "slug": title.slug,
                "name": title.name,
                "name_zh": title.name_zh,
                "year": title.year,
                "director": title.director,
                "license": title.license,
                "attribution": title.attribution,
                "duration_ms": title.duration_ms,
                "shots": session.scalar(
                    select(func.count()).select_from(Shot).where(Shot.title_id == title.id)
                ),
            }
            for title in rows
        ]
    }


@router.get("/api/facets")
def facets(request: Request, session: Session = Depends(get_session)) -> dict:
    filters = _filters_from_query(request)
    return {
        "facets": facet_counts(session, filters),
        "labels": FACET_LABELS,
        "sorts": SORTS,
        "path": filters.path(),
    }


@router.get("/api/shots")
def shots(request: Request, session: Session = Depends(get_session)) -> dict:
    filters = _filters_from_query(request)
    metric_service.bump(session, "search_shots")
    rows, total = query_shots(session, filters)
    return {
        "total": total,
        "path": filters.path(),
        "items": [shot_payload(shot, session.get(Title, shot.title_id)) for shot in rows],
    }


@router.get("/api/browse/{path:path}")
def browse_path(path: str, session: Session = Depends(get_session)) -> dict:
    segments = [segment for segment in path.split("/") if segment]
    filters = parse_filters(segments)
    rows, total = query_shots(session, filters)
    return {
        "path": filters.path(),
        "total": total,
        "items": [shot_payload(shot, session.get(Title, shot.title_id)) for shot in rows],
        "facets": facet_counts(session, filters),
    }


@router.get("/api/shots/{shot_id}")
def shot_detail(shot_id: str, session: Session = Depends(get_session)) -> dict:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在。")
    metric_service.bump(session, "shot_opened")
    title = session.get(Title, shot.title_id)
    payload = shot_payload(shot, title)
    payload["title_attribution"] = title.attribution if title else ""
    return payload


@router.get("/api/shots/{shot_id}/clip")
def shot_clip(
    shot_id: str, fmt: str = Query(default="mp4"), session: Session = Depends(get_session)
):
    try:
        path, media_type = clip_service.export_shot(session, shot_id, fmt)
    except clip_service.ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metric_service.bump(session, "clip_exported")
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/api/lines")
def lines(
    q: str = Query(default=""),
    title: str | None = None,
    limit: int = 20,
    session: Session = Depends(get_session),
) -> dict:
    hits = line_service.search_lines(session, q, limit=min(limit, 50), title_slug=title)
    metric_service.bump(session, "search_lines")
    return {
        "query": q,
        "total": len(hits),
        "items": [line_service.pipeline(session, hit) for hit in hits],
    }


class DeckCreate(BaseModel):
    name: str = "参考板"


class DeckItemCreate(BaseModel):
    kind: str
    ref_id: str
    caption: str | None = None


@router.get("/api/decks")
def deck_index(session: Session = Depends(get_session)) -> dict:
    return {"items": deck_service.list_decks(session)}


@router.post("/api/decks")
def deck_create(payload: DeckCreate, session: Session = Depends(get_session)) -> dict:
    deck = deck_service.create_deck(session, payload.name)
    metric_service.bump(session, "deck_created")
    session.flush()
    return deck_service.deck_payload(session, deck.id)


@router.get("/api/decks/{deck_id}")
def deck_detail(deck_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return deck_service.deck_payload(session, deck_id)
    except deck_service.DeckError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/decks/{deck_id}/items")
def deck_add_item(
    deck_id: str, payload: DeckItemCreate, session: Session = Depends(get_session)
) -> dict:
    try:
        item = deck_service.add_item(
            session, deck_id, payload.kind, payload.ref_id, payload.caption
        )
    except deck_service.DeckError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item_id": item.id, "position": item.position}


@router.delete("/api/decks/{deck_id}/items/{item_id}")
def deck_remove_item(
    deck_id: str, item_id: str, session: Session = Depends(get_session)
) -> dict:
    deck_service.remove_item(session, deck_id, item_id)
    return {"ok": True}


@router.delete("/api/decks/{deck_id}")
def deck_delete(deck_id: str, session: Session = Depends(get_session)) -> dict:
    deck_service.delete_deck(session, deck_id)
    return {"ok": True}


@router.get("/api/decks/{deck_id}/collage")
def deck_collage(
    deck_id: str,
    columns: int = 3,
    session: Session = Depends(get_session),
):
    try:
        path = deck_export.collage(session, deck_id, columns=columns)
    except deck_service.DeckError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@router.get("/decks/{deck_id}/print")
def deck_print(deck_id: str, session: Session = Depends(get_session)):
    try:
        return HTMLResponse(deck_export.print_html(session, deck_id))
    except deck_service.DeckError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class AgentMessage(BaseModel):
    message: str


@router.post("/api/agent")
def agent(payload: AgentMessage, session: Session = Depends(get_session)) -> dict:
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空。")
    metric_service.bump(session, "agent_message")
    reply = agent_service.answer(session, text)
    return reply.payload()


@router.get("/api/metrics")
def metrics(session: Session = Depends(get_session)) -> dict:
    return {"counters": metric_service.snapshot(session)}


@router.get("/api/meta")
def meta() -> dict:
    return {"sorts": SORTS, "facet_labels": FACET_LABELS}


def media_router() -> APIRouter:
    media = APIRouter()
    library = get_settings().library_dir

    @media.get("/media/thumbs/{name}")
    def thumb(name: str):
        path = (library / "thumbs" / name).resolve()
        if not path.is_file() or not str(path).startswith(str((library / "thumbs").resolve())):
            return JSONResponse({"detail": "不存在。"}, status_code=404)
        return FileResponse(path, media_type="image/jpeg")

    @media.get("/media/exports/{name}")
    def export(name: str):
        path = (library / "exports" / name).resolve()
        if not path.is_file() or not str(path).startswith(str((library / "exports").resolve())):
            return JSONResponse({"detail": "不存在。"}, status_code=404)
        media_type = "video/mp4" if path.suffix == ".mp4" else "image/gif"
        return FileResponse(path, media_type=media_type)

    return media


def web_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "web"
