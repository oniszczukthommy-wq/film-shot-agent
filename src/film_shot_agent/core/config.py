"""Runtime settings for the film shot agent."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FILM_AGENT_", env_file=".env", extra="ignore")

    library_dir: Path = ROOT / "data" / "library"
    database_url: str = f"sqlite:///{ROOT / 'data' / 'library' / 'film.sqlite3'}"
    shot_thumb_width: int = 480
    palette_size: int = 5
    max_shots_per_title: int = 400
    scene_threshold: float = 0.35


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
