"""OTel GenAI semantic-convention attributes for LLM spans.

Maverick already had opt-in OTel/Prometheus, but the LLM spans used ad-hoc
attribute names (provider/model) that no OTel-aware backend understands
without custom mapping. observability.gen_ai_attributes() / gen_ai_span_name()
emit the standard gen_ai.* names so traces are legible to Grafana / Honeycomb
/ Arize Phoenix out of the box. These pin the shape (no OTel install needed --
the helpers are pure).
"""
from __future__ import annotations

from maverick import observability as obs


def test_span_name_is_operation_space_model():
    assert obs.gen_ai_span_name("chat", "claude-opus-4-8") == "chat claude-opus-4-8"


def test_request_attributes_use_genai_semconv_keys():
    a = obs.gen_ai_attributes("anthropic", "claude-opus-4-8", max_tokens=4096)
    assert a["gen_ai.operation.name"] == "chat"
    assert a["gen_ai.system"] == "anthropic"
    assert a["gen_ai.request.model"] == "claude-opus-4-8"
    assert a["gen_ai.request.max_tokens"] == 4096
    # response/usage fields omitted when unknown (built in a second pass).
    assert "gen_ai.usage.input_tokens" not in a


def test_usage_attributes_included_when_provided():
    a = obs.gen_ai_attributes(
        "openai", "gpt-5.5", operation="chat",
        response_model="gpt-5.5", input_tokens=1200, output_tokens=340,
    )
    assert a["gen_ai.response.model"] == "gpt-5.5"
    assert a["gen_ai.usage.input_tokens"] == 1200
    assert a["gen_ai.usage.output_tokens"] == 340


def test_exports():
    assert "gen_ai_attributes" in obs.__all__
    assert "gen_ai_span_name" in obs.__all__


def test_llm_span_emits_genai_attributes_when_traced(monkeypatch):
    """End-to-end: LLM.complete sets the gen_ai.* span attributes via a
    captured fake tracer (proves the call site wiring, not just the helper)."""
    captured: dict = {}

    class _FakeSpan:
        def set_attribute(self, k, v):
            captured[k] = v

    import contextlib

    @contextlib.contextmanager
    def _fake_trace_span(name, *, attributes=None):
        captured["__span_name__"] = name
        if attributes:
            captured.update(attributes)
        yield _FakeSpan()

    monkeypatch.setattr(obs, "trace_span", _fake_trace_span)
    monkeypatch.setattr(obs, "record_metric", lambda *a, **k: None)

    from maverick.llm import LLM, LLMResponse, _client_for  # noqa: F401
    import maverick.llm as llm_mod

    class _Usage:
        input_tokens = 11
        output_tokens = 7

    class _Resp:
        text = "ok"
        thinking = None
        tool_calls = []
        usage = _Usage()

    class _FakeClient:
        def complete(self, **kw):
            return _Resp()

    monkeypatch.setattr(llm_mod, "_client_for", lambda provider: _FakeClient())

    out = LLM(model="anthropic:claude-opus-4-8").complete(system="s", messages=[])
    assert out.text == "ok"
    assert captured["__span_name__"] == "chat claude-opus-4-8"
    assert captured["gen_ai.system"] == "anthropic"
    assert captured["gen_ai.request.model"] == "claude-opus-4-8"
    assert captured["gen_ai.usage.input_tokens"] == 11
    assert captured["gen_ai.usage.output_tokens"] == 7
