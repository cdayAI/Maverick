"""Council round-2: dashboard accepts any provider key, not just Anthropic.

Round-1 hard-failed `/chat/send` and `POST /api/v1/goals` if
`ANTHROPIC_API_KEY` wasn't set, even when the user had OpenAI or
Gemini configured. The LLM facade dispatches on model id, so any
valid provider is fine.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    from maverick_dashboard.app import app
    return TestClient(app)


def _strip_provider_env(monkeypatch):
    for v in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
        "OPENROUTER_API_KEY", "MOONSHOT_API_KEY", "DEEPSEEK_API_KEY",
        "XAI_API_KEY",
    ):
        monkeypatch.delenv(v, raising=False)


def test_chat_send_blocks_when_no_provider_key(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    _strip_provider_env(monkeypatch)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    client = _client()
    resp = client.post(
        "/chat/send",
        data={"title": "x"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    # Actionable message: pointers to `maverick init` and the env vars.
    assert "maverick init" in detail
    assert "ANTHROPIC_API_KEY" in detail or "OPENAI_API_KEY" in detail


def test_chat_send_accepts_openai_key(monkeypatch, tmp_path):
    """Previously this would 400 because the check looked only at ANTHROPIC."""
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    _strip_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    client = _client()
    resp = client.post(
        "/chat/send",
        data={"title": "x"},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert resp.status_code == 303  # redirect to /chat/goal/{id}


def test_api_goals_blocks_when_no_provider_key(monkeypatch, tmp_path):
    from maverick import world_model
    monkeypatch.setattr(world_model, "DEFAULT_DB", tmp_path / "world.db")
    monkeypatch.delenv("MAVERICK_DASHBOARD_TOKEN", raising=False)
    _strip_provider_env(monkeypatch)
    from maverick_dashboard import app as dash_app
    dash_app._world_cache.clear()
    client = _client()
    resp = client.post(
        "/api/v1/goals",
        json={"title": "x"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 400
    assert "maverick init" in resp.json()["detail"]
