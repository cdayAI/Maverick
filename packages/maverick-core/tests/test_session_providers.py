"""Session-provider unit tests.

Covers:
  - cookie_store round-trip + perms enforcement
  - registry dispatch + aliases
  - ChatGPTSessionClient request shape + SSE parsing (mocked httpx)
  - tool-use rejection (consumer chat doesn't support tools)
  - LLM facade routes chatgpt-session:* specs to the session client
"""
from __future__ import annotations

import os
import stat
from unittest.mock import patch

import pytest


# ---------- cookie_store ----------

def test_cookie_store_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store

    blob = {"cookies": {"__Secure-next-auth.session-token": "abc123"}}
    path = cookie_store.save_session("chatgpt-session", blob)
    assert path.exists()
    # Mode 0600 enforced.
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = cookie_store.load_session("chatgpt-session")
    assert loaded["cookies"]["__Secure-next-auth.session-token"] == "abc123"
    assert "saved_at" in loaded


def test_cookie_store_no_session_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    assert cookie_store.load_session("chatgpt-session") is None


def test_cookie_store_rejects_world_readable(tmp_path, monkeypatch):
    """Refuses to load a session file with relaxed perms."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store

    path = cookie_store.save_session("chatgpt-session", {"cookies": {"k": "v"}})
    os.chmod(path, 0o644)
    with pytest.raises(PermissionError, match="mode"):
        cookie_store.load_session("chatgpt-session")


def test_cookie_store_clear_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    cookie_store.save_session("chatgpt-session", {"cookies": {"a": "1"}})
    cookie_store.save_session("kimi-session", {"cookies": {"b": "2"}})
    assert sorted(cookie_store.list_sessions()) == ["chatgpt-session", "kimi-session"]
    assert cookie_store.clear_session("chatgpt-session") is True
    assert cookie_store.clear_session("chatgpt-session") is False
    assert cookie_store.list_sessions() == ["kimi-session"]


def test_cookie_store_atomic_write(tmp_path, monkeypatch):
    """No half-written temp file should remain after save."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    cookie_store.save_session("chatgpt-session", {"cookies": {"k": "v"}})
    leftovers = list(tmp_path.glob("**/*.tmp"))
    assert leftovers == [], f"temp files leaked: {leftovers}"


def test_cookie_store_rejects_path_traversal(tmp_path, monkeypatch):
    """Provider names with slashes / .. can't escape the session dir."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    # Should not write outside ~/.maverick/sessions/
    p = cookie_store.save_session("../../evil", {"cookies": {"k": "v"}})
    sessions_dir = tmp_path / ".maverick" / "sessions"
    assert sessions_dir in p.parents


# ---------- registry ----------

def test_is_session_provider():
    from maverick.session_providers import is_session_provider
    assert is_session_provider("chatgpt-session")
    assert is_session_provider("chatgpt")
    assert is_session_provider("openai-session")
    assert is_session_provider("CHATGPT-SESSION")  # case-insensitive
    assert not is_session_provider("openai")  # BYOK, not session
    assert not is_session_provider("anthropic")
    assert not is_session_provider("")


def test_get_session_client_unknown_raises():
    from maverick.session_providers import get_session_client
    with pytest.raises(ValueError, match="Available"):
        get_session_client("not-a-real-session")


def test_get_session_client_requires_stored_session(tmp_path, monkeypatch):
    """No cookie file -> instantiation fails with actionable message."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import get_session_client
    with pytest.raises(RuntimeError, match="No ChatGPT session stored"):
        get_session_client("chatgpt-session")


# ---------- ChatGPTSessionClient ----------

class _FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            req = httpx.Request("GET", "http://x")
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=req,
                response=httpx.Response(self.status_code),
            )


class _FakeClient:
    """Drop-in for httpx.Client inside the adapter."""
    def __init__(self, *, auth_response=None, conv_response=None):
        self._auth = auth_response
        self._conv = conv_response
        self.calls: list[tuple[str, str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, headers or {}))
        return self._auth

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, headers or {}))
        self.last_post_body = json
        return self._conv


def _stub_session(tmp_path, monkeypatch, *, access_token=None):
    monkeypatch.setenv("HOME", str(tmp_path))
    from maverick.session_providers import cookie_store
    blob = {"cookies": {"__Secure-next-auth.session-token": "fake-cookie"}}
    if access_token:
        blob["access_token"] = access_token
    cookie_store.save_session("chatgpt-session", blob)


def _sse(*chunks: str) -> str:
    """Build an SSE response body from text chunks (each a cumulative reply)."""
    import json
    lines = []
    for chunk in chunks:
        event = {"message": {"content": {"parts": [chunk]}}}
        lines.append("data: " + json.dumps(event))
    lines.append("data: [DONE]")
    return "\n".join(lines)


def test_chatgpt_session_text_completion(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch)
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    auth_resp = _FakeResponse(200, json_data={"accessToken": "token-xyz"})
    conv_resp = _FakeResponse(200, text=_sse("Hi", "Hi there", "Hi there, friend!"))
    fake = _FakeClient(auth_response=auth_resp, conv_response=conv_resp)

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        resp = client.complete(
            system="be brief",
            messages=[{"role": "user", "content": "say hi"}],
        )

    assert resp.text == "Hi there, friend!"  # last cumulative chunk wins
    assert resp.tool_calls == []
    assert resp.stop_reason == "end_turn"


def test_chatgpt_session_uses_cached_access_token(tmp_path, monkeypatch):
    """If access_token is in the session blob, don't hit /api/auth/session."""
    _stub_session(tmp_path, monkeypatch, access_token="cached-token-9")
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    conv_resp = _FakeResponse(200, text=_sse("ok"))
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        client.complete(system="", messages=[{"role": "user", "content": "yo"}])

    # No GET to /api/auth/session.
    methods = [c[0] for c in fake.calls]
    assert methods == ["POST"]
    # POST carried the cached bearer.
    post_headers = fake.calls[0][2]
    assert post_headers["Authorization"] == "Bearer cached-token-9"


def test_chatgpt_session_rejects_tool_use(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient
    client = ChatGPTSessionClient()
    with pytest.raises(NotImplementedError, match="tool-use"):
        client.complete(
            system="", messages=[{"role": "user", "content": "x"}],
            tools=[{"name": "calc", "input_schema": {}}],
        )


def test_chatgpt_session_401_actionable_error(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch)
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    auth_resp = _FakeResponse(401)
    fake = _FakeClient(auth_response=auth_resp)
    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        with pytest.raises(RuntimeError, match="(expired|re-capture)"):
            client.complete(system="", messages=[{"role": "user", "content": "x"}])


def test_chatgpt_session_429_rate_limit(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    conv_resp = _FakeResponse(429)
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)
    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        with pytest.raises(RuntimeError, match="rate-limited"):
            client.complete(system="", messages=[{"role": "user", "content": "x"}])


def test_chatgpt_session_request_body_shape(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    conv_resp = _FakeResponse(200, text=_sse("ok"))
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)
    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        client.complete(
            system="sys", messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
        )

    body = fake.last_post_body
    assert body["action"] == "next"
    assert body["model"] == "gpt-4o-mini"
    assert len(body["messages"]) == 1
    msg = body["messages"][0]
    assert msg["author"]["role"] == "user"
    assert msg["content"]["content_type"] == "text"
    # Prompt flattening preserved system + user content.
    flat = msg["content"]["parts"][0]
    assert "[SYSTEM]" in flat
    assert "sys" in flat
    assert "hello" in flat


def test_chatgpt_session_budget_recorded(tmp_path, monkeypatch):
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.budget import Budget
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient

    conv_resp = _FakeResponse(200, text=_sse("hello there, friend"))
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)
    budget = Budget(max_dollars=10.0)

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        client = ChatGPTSessionClient()
        client.complete(
            system="", messages=[{"role": "user", "content": "hi"}],
            budget=budget,
        )

    # Best-effort: output_tokens should be >0 (approximated from char count).
    assert budget.output_tokens > 0


# ---------- LLM facade integration ----------

def test_llm_facade_routes_chatgpt_session(tmp_path, monkeypatch):
    """LLM('chatgpt-session:gpt-4o').complete() must dispatch to the
    session client, not the regular openai client."""
    _stub_session(tmp_path, monkeypatch, access_token="t")
    from maverick.llm import LLM

    llm = LLM(model="chatgpt-session:gpt-4o")
    conv_resp = _FakeResponse(200, text=_sse("routed!"))
    fake = _FakeClient(auth_response=None, conv_response=conv_resp)

    import httpx
    with patch.object(httpx, "Client", return_value=fake):
        resp = llm.complete(system="", messages=[{"role": "user", "content": "go"}])
    assert resp.text == "routed!"
    # The cached client is a ChatGPTSessionClient, not OpenAIClient.
    from maverick.session_providers.chatgpt_session import ChatGPTSessionClient
    assert isinstance(llm._clients["chatgpt-session"], ChatGPTSessionClient)
