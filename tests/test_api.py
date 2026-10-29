"""HTTP surface."""

import pytest
from fastapi.testclient import TestClient

from film_shot_agent.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as active:
        yield active


def test_health_counts_seeded_library(client):
    body = client.get("/api/health").json()
    assert body == {"titles": 2, "shots": 31, "lines": 4}


def test_facets_are_labelled(client):
    body = client.get("/api/facets").json()
    assert "color_temp" in body["facets"]
    assert body["labels"]["color_temp"] == "色调"


def test_shots_endpoint_returns_palette(client):
    body = client.get("/api/shots", params={"color_temp": "cool"}).json()
    assert body["total"] == 10
    assert body["items"][0]["look"]["palette"]


def test_path_encoded_browse_matches_query_api(client):
    direct = client.get("/api/shots", params={"color_temp": "cool", "brightness": "dark"}).json()
    encoded = client.get("/api/browse/color_temp/cool/brightness/dark").json()
    assert direct["total"] == encoded["total"]


def test_unknown_shot_is_404(client):
    assert client.get("/api/shots/nope").status_code == 404


def test_deck_lifecycle(client):
    created = client.post("/api/decks", json={"name": "面试演示"}).json()
    deck_id = created["id"]
    added = client.post(
        f"/api/decks/{deck_id}/items", json={"kind": "shot", "ref_id": "alpha-000"}
    )
    assert added.status_code == 200
    detail = client.get(f"/api/decks/{deck_id}").json()
    assert detail["items"][0]["shot"]["id"] == "alpha-000"
    assert client.delete(f"/api/decks/{deck_id}").json()["ok"] is True


def test_deck_rejects_unknown_shot(client):
    deck = client.post("/api/decks", json={"name": "x"}).json()
    response = client.post(
        f"/api/decks/{deck['id']}/items", json={"kind": "shot", "ref_id": "ghost"}
    )
    assert response.status_code == 400


def test_agent_endpoint_exposes_trace(client):
    body = client.post("/api/agent", json={"message": "冷色调镜头"}).json()
    assert body["trace"][0]["tool"] == "search_shots"
    assert body["path"].startswith("/color_temp/cool")


def test_agent_rejects_empty_message(client):
    assert client.post("/api/agent", json={"message": "  "}).status_code == 400


def test_metrics_never_store_terms(client):
    body = client.get("/api/metrics").json()
    assert set(body["counters"]).issuperset({"agent_message", "search_shots"})
    assert all(isinstance(value, int) for value in body["counters"].values())
