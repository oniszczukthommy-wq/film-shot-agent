FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    FILM_AGENT_DEMO_MODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY data/library/demo.sqlite3 ./data/library/demo.sqlite3
COPY data/library/thumbs ./data/library/thumbs
COPY data/library/subs ./data/library/subs

# The demo index is read-only source material; the app writes to its own copy.
RUN cp data/library/demo.sqlite3 data/library/film.sqlite3 \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn film_shot_agent.main:app --app-dir src --host 0.0.0.0 --port ${PORT:-8000}"]
