"""Regression tests for bug-hunt wave-6 fixes (core side)."""
from __future__ import annotations


class TestSecretDetectorBearer:
    def test_base64_bearer_detected(self):
        from maverick.safety.secret_detector import scan
        m = scan("Authorization: Bearer abcd+efgh/ijkl==mnopQRSTuvwx")
        assert any(x.name == "bearer_header" for x in m)


class TestPrivacyAnonStr:
    def test_string_false_disables(self, monkeypatch):
        import maverick.config as cfg
        from maverick import privacy
        monkeypatch.delenv("MAVERICK_ANON", raising=False)
        monkeypatch.setattr(cfg, "load_config",
                            lambda: {"privacy": {"anonymous": "false"}})
        assert privacy.anon_enabled() is False

    def test_string_true_enables(self, monkeypatch):
        import maverick.config as cfg
        from maverick import privacy
        monkeypatch.delenv("MAVERICK_ANON", raising=False)
        monkeypatch.setattr(cfg, "load_config",
                            lambda: {"privacy": {"anonymous": "true"}})
        assert privacy.anon_enabled() is True


class TestReasoningContentPreserved:
    def test_openai_response_reasoning_content_to_thinking(self):
        from maverick.providers.openai_provider import OpenAIClient

        class _Msg:
            content = "the answer"
            reasoning_content = "step-by-step CoT"
            tool_calls = None

        class _Choice:
            message = _Msg()
            finish_reason = "stop"

        class _Resp:
            choices = [_Choice()]
            usage = None

        out = OpenAIClient._from_response(_Resp(), None, model="deepseek-reasoner")
        assert out.thinking == "step-by-step CoT"
        assert out.text == "the answer"
