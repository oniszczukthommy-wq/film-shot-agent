"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from film_shot_agent.api.routes import media_router, router, web_dir
from film_shot_agent.core.db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(
    title="Film Shot Agent",
    version="0.1.0",
    description="Cinematic shot & line search",
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(media_router())

_STATIC = web_dir()
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = Path(web_dir()) / "index.html"
    if not page.exists():
        return HTMLResponse("<h1>UI 尚未生成</h1>", status_code=503)
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/browse/{path:path}", response_class=HTMLResponse)
def browse_page(path: str) -> HTMLResponse:  # noqa: ARG001 - shareable URL surface
    """Shareable path-encoded queries land on the same single-page UI."""
    return index()


@app.get("/favicon.ico")
def favicon():
    icon = Path(web_dir()) / "favicon.svg"
    if icon.exists():
        return FileResponse(icon, media_type="image/svg+xml")
    return HTMLResponse(status_code=204)
