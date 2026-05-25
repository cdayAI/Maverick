"""REST API endpoint tests."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from maverick_dashboard.app import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_world(tmp_path, monkeypatch):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    yield


class TestGoals:
    def test_create_requires_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        resp = client.post("/api/v1/goals", json={"title": "hi"})
        assert resp.status_code == 400
        assert "ANTHROPIC_API_KEY" in resp.json()["detail"]

    def test_create_returns_pending(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        # Replace the runner so we don't actually call Anthropic.
        import maverick_dashboard.api as api_mod
        called = []
        monkeypatch.setattr(api_mod, "_run_goal_in_thread", lambda g: called.append(g))
        resp = client.post("/api/v1/goals", json={
            "title": "test goal", "description": "x", "max_dollars": 1.0,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["title"] == "test goal"
        assert called == [data["id"]]

    def test_list_returns_array(self):
        resp = client.get("/api/v1/goals")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_unknown_404(self):
        resp = client.get("/api/v1/goals/999999")
        assert resp.status_code == 404

    def test_events_for_unknown_404(self):
        resp = client.get("/api/v1/goals/999999/events")
        assert resp.status_code == 404


class TestFacts:
    def test_get_empty_initially(self):
        resp = client.get("/api/v1/facts")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_set_then_get(self):
        resp = client.post("/api/v1/facts", json={"key": "city", "value": "Lisbon"})
        assert resp.status_code == 204
        resp = client.get("/api/v1/facts")
        assert resp.json() == {"city": "Lisbon"}

    def test_upsert_overwrites(self):
        client.post("/api/v1/facts", json={"key": "city", "value": "Lisbon"})
        client.post("/api/v1/facts", json={"key": "city", "value": "Tokyo"})
        assert client.get("/api/v1/facts").json() == {"city": "Tokyo"}


class TestSkills:
    def test_list_returns_array(self):
        resp = client.get("/api/v1/skills")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_install_bad_source_400(self):
        resp = client.post("/api/v1/skills", json={"source": "/nonexistent/path.md"})
        assert resp.status_code == 400

    def test_remove_unknown_404(self):
        resp = client.delete("/api/v1/skills/does-not-exist")
        assert resp.status_code == 404


class TestSpend:
    def test_returns_total_and_episodes(self):
        resp = client.get("/api/v1/spend")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "episodes" in data
        assert isinstance(data["episodes"], list)


class TestOpenAPI:
    def test_openapi_schema_served(self):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        # Sanity: every v1 endpoint shows up in the spec.
        paths = spec.get("paths", {})
        for required in (
            "/api/v1/goals", "/api/v1/goals/{goal_id}", "/api/v1/facts",
            "/api/v1/skills", "/api/v1/spend",
        ):
            assert required in paths, f"missing {required}"

    def test_docs_served(self):
        resp = client.get("/docs")
        assert resp.status_code == 200
