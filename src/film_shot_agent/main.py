"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from film_shot_agent.api.chat_routes import router as chat_router
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
app.include_router(chat_router)
app.include_router(media_router())


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """One error shape for every bad request: {"error": {"code", "message"}}."""
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", [])[1:]) or "body"
    message = str(first.get("msg") or "请求参数不合法。")
    return JSONResponse(
        {"error": {"code": "invalid_request", "message": f"{location}: {message}"}},
        status_code=422,
    )

_STATIC = web_dir()
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """The product is the dialog: quote → film, ratings, where to watch."""
    return _page("chat.html")


@app.get("/ask")
def ask() -> RedirectResponse:
    """The old research UI is superseded by the one-dialog chat page."""
    return RedirectResponse("/", status_code=302)


@app.get("/chat", response_class=HTMLResponse)
def chat_page() -> HTMLResponse:
    """Alias for the home page, kept for old links."""
    return _page("chat.html")


@app.get("/library", response_class=HTMLResponse)
def library_page() -> HTMLResponse:
    """The licensed shot library lives beside the product, not at the root."""
    return _page("index.html")


def _page(name: str) -> HTMLResponse:
    page = Path(web_dir()) / name
    if not page.exists():
        return HTMLResponse("<h1>UI 尚未生成</h1>", status_code=503)
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/browse/{path:path}", response_class=HTMLResponse)
def browse_page(path: str) -> HTMLResponse:  # noqa: ARG001 - shareable URL surface
    """Shareable path-encoded queries land on the same single-page UI."""
    return _page("index.html")


@app.get("/favicon.ico")
def favicon():
    icon = Path(web_dir()) / "favicon.svg"
    if icon.exists():
        return FileResponse(icon, media_type="image/svg+xml")
    return HTMLResponse(status_code=204)
