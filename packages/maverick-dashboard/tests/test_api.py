"""REST API endpoint tests.

v0.1.6: the BackgroundTask runner is now `maverick.runner.run_goal_in_thread`
with signature ``(goal_id, max_dollars, max_wall_seconds, max_depth)``,
so the create_returns_pending monkeypatch takes 4 positional args (was 1).
"""
from __future__ import annotations

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
        # Patch the shared runner so we don't actually call Anthropic.
        # The new signature is (goal_id, max_dollars, max_wall_seconds, max_depth).
        import maverick.runner as runner_mod
        called = []
        def fake_run(goal_id, max_dollars=2.0, max_wall_seconds=1800.0, max_depth=3):
            called.append((goal_id, max_dollars, max_wall_seconds, max_depth))
        monkeypatch.setattr(runner_mod, "run_goal_in_thread", fake_run)
        resp = client.post("/api/v1/goals", json={
            "title": "test goal", "description": "x", "max_dollars": 1.0,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["title"] == "test goal"
        assert len(called) == 1
        assert called[0][0] == data["id"]
        # Verify payload's max_dollars propagated (the fix from the council
        # security review).
        assert called[0][1] == 1.0

    def test_create_clamps_max_dollars(self, monkeypatch):
        """Pydantic Field bounds reject values outside [0, 100]."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
        resp = client.post("/api/v1/goals", json={
            "title": "big spend", "max_dollars": 10_000.0,
        })
        # 422 = Pydantic validation error
        assert resp.status_code == 422

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


class TestAnswer:
    """POST /api/v1/goals/{id}/answer now takes a JSON body (v0.1.6)."""

    def test_answer_unknown_question_404(self, tmp_path, monkeypatch):
        from maverick import world_model
        monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
        w = world_model.WorldModel(tmp_path / "world.db")
        gid = w.create_goal("test", "")
        resp = client.post(
            f"/api/v1/goals/{gid}/answer",
            json={"question_id": 9999, "answer": "x"},
        )
        assert resp.status_code == 404

    def test_answer_missing_body_422(self, tmp_path, monkeypatch):
        from maverick import world_model
        monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
        w = world_model.WorldModel(tmp_path / "world.db")
        gid = w.create_goal("test", "")
        # No body -> Pydantic validation 422 (was query-string-only before).
        resp = client.post(f"/api/v1/goals/{gid}/answer")
        assert resp.status_code == 422


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

    def test_install_bare_path_rejected(self):
        """REST callers can't POST {"source": "/etc/passwd"} (security fix)."""
        resp = client.post("/api/v1/skills", json={"source": "/etc/passwd"})
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"]

    def test_install_file_scheme_rejected(self):
        resp = client.post("/api/v1/skills", json={"source": "file:///etc/passwd"})
        assert resp.status_code == 400

    def test_install_bad_gh_format_rejected(self):
        resp = client.post("/api/v1/skills", json={"source": "gh:not-valid"})
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
        paths = spec.get("paths", {})
        for required in (
            "/api/v1/goals", "/api/v1/goals/{goal_id}", "/api/v1/facts",
            "/api/v1/skills", "/api/v1/spend",
        ):
            assert required in paths, f"missing {required}"

    def test_docs_served(self):
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_exempt_from_bearer_auth(self, monkeypatch):
        """OpenAPI tooling needs /openapi.json without a token."""
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/openapi.json")
        assert resp.status_code == 200

    def test_docs_exempt_from_bearer_auth(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_api_endpoint_requires_bearer_when_token_set(self, monkeypatch):
        """Council test-coverage finding: /api/v1 was never tested with auth.

        Silent auth bypass on the API would be catastrophic; this test
        catches that regression class.
        """
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/api/v1/goals")
        assert resp.status_code == 401

    def test_api_endpoint_with_bearer_succeeds(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get(
            "/api/v1/goals",
            headers={"Authorization": "Bearer s3cr3t"},
        )
        assert resp.status_code == 200

    def test_api_endpoint_with_query_token_succeeds(self, monkeypatch):
        """Phone browsers bookmark `?token=...`; that has to authenticate."""
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/api/v1/goals?token=s3cr3t")
        assert resp.status_code == 200

    def test_api_endpoint_with_wrong_bearer_rejected(self, monkeypatch):
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get(
            "/api/v1/goals",
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401

    def test_healthz_exempt_from_bearer_auth(self, monkeypatch):
        """Monitors must be able to ping /healthz without a token."""
        monkeypatch.setenv("MAVERICK_DASHBOARD_TOKEN", "s3cr3t")
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
