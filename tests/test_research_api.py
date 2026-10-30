"""HTTP surface for the research layer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from film_shot_agent.main import app
from film_shot_agent.services import research as research_service


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as active:
        yield active


def test_home_is_the_chat_page(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "问片" in page.text
    assert "/static/chat.js" in page.text
    assert client.get("/chat").status_code == 200


def test_ask_redirects_home_and_library_still_works(client):
    response = client.get("/ask", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    library = client.get("/library")
    assert library.status_code == 200
    assert "/static/app.js" in library.text


def test_meta_reports_research_without_secrets(client):
    body = client.get("/api/meta").json()
    assert "research" in body
    assert body["research"]["enabled"] is True
    assert "key" not in str(body).lower()
    assert "sk-" not in str(body)


def test_research_endpoint_returns_payload(client, monkeypatch):
    def fake_research(session, text):
        assert text == "盗梦空间好看吗"
        return {"answer": "好看", "intent": "rating", "titles": [], "citations": []}

    monkeypatch.setattr(research_service, "research", fake_research)
    response = client.post("/api/research", json={"message": "盗梦空间好看吗"})
    assert response.status_code == 200
    assert response.json()["answer"] == "好看"


def test_research_unavailable_uses_error_envelope(client, monkeypatch):
    def fake_research(session, text):
        raise research_service.ResearchUnavailable("未配置模型 Key，问片功能暂时不可用。")

    monkeypatch.setattr(research_service, "research", fake_research)
    response = client.post("/api/research", json={"message": "找部片"})
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "research_unavailable",
            "message": "未配置模型 Key，问片功能暂时不可用。",
        }
    }


def test_research_failure_does_not_leak_internals(client, monkeypatch):
    def fake_research(session, text):
        raise research_service.ResearchError("模型调用失败，请稍后再试。")

    monkeypatch.setattr(research_service, "research", fake_research)
    response = client.post("/api/research", json={"message": "找部片"})
    assert response.status_code == 502
    assert "error" in response.json()
    assert "sk-" not in response.text
