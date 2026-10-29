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

    # Research layer ("问片"). Secrets stay in .env / process env only.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 45.0
    llm_max_steps: int = 6
    search_provider: str = "auto"  # auto | tavily | brave | duckduckgo
    search_api_key: str = ""
    tmdb_api_key: str = ""
    region: str = "CN"
    research_cache_ttl: int = 3600
    research_max_question: int = 300
    research_tool_budget: int = 10
    demo_mode: bool = False

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_api_key.strip())

    @property
    def has_tmdb(self) -> bool:
        return bool(self.tmdb_api_key.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
