"""Video streaming: range support, missing files, unknown titles."""

import pytest
from fastapi.testclient import TestClient

from film_shot_agent.core.config import get_settings
from film_shot_agent.domain.models import Title
from film_shot_agent.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as active:
        yield active


def test_unknown_title_is_404(client):
    assert client.get("/media/video/ghost").status_code == 404


def _clear_web_copies() -> None:
    web = get_settings().library_dir / "web"
    if web.exists():
        for item in web.glob("*.mp4"):
            item.unlink()


def test_missing_source_file_is_explained(client, session, tmp_path):
    _clear_web_copies()
    session.get(Title, "t-alpha").source_file = str(tmp_path / "gone.mp4")
    session.commit()
    response = client.get("/media/video/alpha")
    assert response.status_code == 404
    assert "源文件不在本机" in response.json()["detail"]


def test_serves_web_copy_with_range(client, session):
    _clear_web_copies()
    library = get_settings().library_dir
    web = library / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "alpha.mp4").write_bytes(b"0123456789" * 100)

    full = client.get("/media/video/alpha")
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"

    part = client.get("/media/video/alpha", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.headers["content-range"] == "bytes 10-19/1000"
    assert part.content == b"0123456789"

    _clear_web_copies()


def test_falls_back_to_master_file_when_no_web_copy(client, session, tmp_path):
    _clear_web_copies()
    master = tmp_path / "beta.mov"
    master.write_bytes(b"master-bytes")
    session.get(Title, "t-beta").source_file = str(master)
    session.commit()

    response = client.get("/media/video/beta")
    assert response.status_code == 200
    assert response.content == b"master-bytes"
