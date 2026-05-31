"""User-typed config values must apply regardless of case/whitespace.

profile/backend/provider etc. come from hand-edited TOML (or CLI flags) and
were compared against lowercase literals, so "Docker" / "Anthropic:" silently
misapplied. These tests pin the normalization at the two highest-impact
chokepoints:

  - build_sandbox(): a mis-cased backend must NOT silently degrade to the
    unsandboxed local backend (a security downgrade), and an unrecognized
    backend must warn loudly instead of failing quiet.
  - llm._parse_spec(): a mis-cased / aliased provider must canonicalize so the
    case-sensitive API-key lookup resolves (not just client creation).
"""
from __future__ import annotations

import logging

import maverick.sandbox as sandbox_mod
from maverick.llm import _parse_spec
from maverick.sandbox import LocalBackend, build_sandbox


class TestSandboxBackendCasing:
    # Patch the container backends to sentinels: DockerBackend/PodmanBackend
    # verify their runtime in __init__ (raise when absent), so we test the
    # selection logic in isolation -- and a sentinel return sharply proves the
    # branch taken (vs a silent fall-through to the real LocalBackend).
    def test_mixed_case_docker_resolves_to_docker_not_local(self, monkeypatch):
        monkeypatch.setattr(sandbox_mod, "DockerBackend", lambda **kw: "DOCKER")
        assert build_sandbox(backend="Docker") == "DOCKER"

    def test_surrounding_whitespace_and_case_tolerated(self, monkeypatch):
        monkeypatch.setattr(sandbox_mod, "PodmanBackend", lambda **kw: "PODMAN")
        assert build_sandbox(backend="  PODMAN  ") == "PODMAN"

    def test_unknown_backend_falls_back_to_local_with_named_warning(self, monkeypatch, caplog):
        # Silence the generic local-unsandboxed advisory so the assertion only
        # sees the unrecognized-backend warning my fix adds.
        monkeypatch.setenv("MAVERICK_SUPPRESS_SANDBOX_WARNING", "1")
        with caplog.at_level(logging.WARNING, logger="maverick.sandbox"):
            sb = build_sandbox(backend="dokcer")  # typo
        assert isinstance(sb, LocalBackend)
        assert "unrecognized sandbox backend" in caplog.text
        assert "dokcer" in caplog.text

    def test_explicit_local_does_not_warn_unrecognized(self, monkeypatch, caplog):
        monkeypatch.setenv("MAVERICK_SUPPRESS_SANDBOX_WARNING", "1")
        with caplog.at_level(logging.WARNING, logger="maverick.sandbox"):
            sb = build_sandbox(backend="Local")
        assert isinstance(sb, LocalBackend)
        assert "unrecognized sandbox backend" not in caplog.text


class TestParseSpecProviderCasing:
    def test_mixed_case_provider_canonicalizes(self):
        assert _parse_spec("Anthropic:claude-opus-4-7") == ("anthropic", "claude-opus-4-7")

    def test_advertised_alias_resolves(self):
        # 'claude' and 'kimi' are documented aliases (providers._PROVIDER_ALIASES).
        assert _parse_spec("claude:some-model") == ("anthropic", "some-model")
        assert _parse_spec("kimi:k2") == ("moonshot", "k2")

    def test_bare_model_id_defaults_to_anthropic(self):
        assert _parse_spec("claude-opus-4-7") == ("anthropic", "claude-opus-4-7")

    def test_only_first_colon_splits_provider(self):
        # Model ids can contain colons; split(":", 1) must preserve them.
        assert _parse_spec("openai:org/model:v2") == ("openai", "org/model:v2")
