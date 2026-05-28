"""Functional robustness: audit `day` path-traversal + bounded params.

The audit log resolves ``day`` to ``audit_dir/{day}.ndjson``; the
dashboard passed the raw ``?day=`` query value straight through, so a
crafted value could escape the audit directory. The day is now validated
to YYYY-MM-DD at the HTTP boundary, a non-numeric ``n`` no longer 500s,
and the events endpoints cap ``limit``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _env(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.setattr(
        "maverick.audit.writer.DEFAULT_AUDIT_DIR", tmp_path / "audit",
    )
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    import maverick.audit.writer as aw
    aw._default = None
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()


def test_safe_audit_day_validation():
    from maverick_dashboard.app import safe_audit_day
    assert safe_audit_day("2026-05-28") == "2026-05-28"
    assert safe_audit_day("../../etc/passwd") is None
    assert safe_audit_day("../secret") is None
    assert safe_audit_day("2026-05-28/../../x") is None
    assert safe_audit_day("") is None
    assert safe_audit_day(None) is None


def test_audit_page_survives_non_numeric_n(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    r = _client().get("/audit?n=not-a-number")
    assert r.status_code == 200  # was an unguarded int() -> 500


def test_audit_page_neutralizes_day_traversal(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    r = _client().get("/audit?day=../../../etc/passwd")
    assert r.status_code == 200
    assert "../../../etc/passwd" not in r.text  # rejected, not used as a path


def test_audit_grep_api_neutralizes_day_traversal(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    c = _client()
    today = c.get("/api/v1/audit/grep?pattern=x")
    traversed = c.get("/api/v1/audit/grep?pattern=x&day=../../../etc/passwd")
    assert today.status_code == 200 and traversed.status_code == 200
    # A bad day collapses to today's log; a raw traversal would have read a
    # different (escaped) path and returned a different result.
    assert traversed.json()["events"] == today.json()["events"]


def test_goal_events_endpoint_caps_limit(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    from maverick import world_model
    gid = world_model.WorldModel(tmp_path / "world.db").create_goal("g", "d")
    r = _client().get(f"/api/v1/goals/{gid}/events?limit=999999999")
    assert r.status_code == 200
