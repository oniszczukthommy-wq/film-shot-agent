"""A fresh clone should browse the bundled demo index without running ingest."""

from pathlib import Path

from film_shot_agent.core import config, db


def test_falls_back_to_demo_index(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FILM_AGENT_LIBRARY_DIR", str(tmp_path))
    monkeypatch.setenv("FILM_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'film.sqlite3'}")
    config.get_settings.cache_clear()
    (tmp_path / "demo.sqlite3").write_bytes(b"")
    assert db.resolve_database_url().endswith("demo.sqlite3")
    config.get_settings.cache_clear()


def test_keeps_configured_url_when_the_real_index_exists(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FILM_AGENT_LIBRARY_DIR", str(tmp_path))
    monkeypatch.setenv("FILM_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'film.sqlite3'}")
    config.get_settings.cache_clear()
    (tmp_path / "film.sqlite3").write_bytes(b"")
    (tmp_path / "demo.sqlite3").write_bytes(b"")
    assert db.resolve_database_url().endswith("film.sqlite3")
    config.get_settings.cache_clear()


def test_ingest_can_opt_out_of_the_fallback(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FILM_AGENT_LIBRARY_DIR", str(tmp_path))
    monkeypatch.setenv("FILM_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'film.sqlite3'}")
    config.get_settings.cache_clear()
    db.reset_for_tests()
    (tmp_path / "demo.sqlite3").write_bytes(b"")
    db.init_db(allow_demo_fallback=False)
    assert (tmp_path / "film.sqlite3").exists(), "建索引必须写 film.sqlite3，不能覆盖 demo"
    assert (tmp_path / "demo.sqlite3").stat().st_size == 0
    db.reset_for_tests()
    config.get_settings.cache_clear()
