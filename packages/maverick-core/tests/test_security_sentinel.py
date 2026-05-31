"""Security self-audit ("Sentinel") tests.

Covers: every invariant passes on the current tree, the audit is robust when
research has no backend, research output is treated as untrusted (scrubbed),
and the report renders.
"""
from __future__ import annotations

from maverick import security_sentinel as ss

# ---- invariants ------------------------------------------------------------

def test_all_invariants_pass_on_current_tree():
    results = ss.run_invariants()
    assert results, "expected at least one invariant"
    failures = [r for r in results if not r.passed and not r.skipped]
    assert not failures, "broken invariants: " + ", ".join(
        f"{r.id}: {r.detail}" for r in failures
    )


def test_ssrf_invariant_blocks_loopback():
    r = ss._inv_ssrf_pinning()
    assert r.passed and not r.skipped
    assert r.severity == "critical"


def test_a2a_invariant_is_fail_closed(monkeypatch):
    # The check manages its own env, but make sure ambient env doesn't leak in.
    monkeypatch.delenv("MAVERICK_A2A_TOKEN", raising=False)
    monkeypatch.delenv("MAVERICK_A2A_ALLOW_UNAUTHENTICATED", raising=False)
    r = ss._inv_a2a_auth_fail_closed()
    assert r.passed, r.detail


def test_shield_evasion_invariant():
    r = ss._inv_shield_evasion_resistant()
    # maverick-shield is a dev dependency here, so it should actually run.
    assert r.passed, r.detail


def test_webhook_verify_invariant():
    r = ss._inv_inbound_webhook_constant_time()
    assert r.passed, r.detail


def test_no_shell_true_in_tools_invariant():
    r = ss._inv_no_shell_true_in_tools()
    # Either it ran and is clean, or the source tree wasn't available.
    assert r.passed or r.skipped, r.detail


# ---- research --------------------------------------------------------------

def test_brief_reflects_enabled_surface(monkeypatch):
    cfg = {
        "sandbox": {"backend": "ssh"},
        "channels": {"discord": {"enabled": True}, "slack": {"enabled": False}},
    }
    monkeypatch.setattr(ss, "build_research_brief",
                        ss.build_research_brief)  # keep real fn
    import maverick.config as config
    monkeypatch.setattr(config, "load_config", lambda *a, **k: cfg)
    topics = ss.build_research_brief()
    ids = {t.id for t in topics}
    assert "mcp" in ids and "a2a" in ids        # static high-value topics
    assert "sandbox-ssh" in ids                  # dynamic: enabled backend
    assert "channel-discord" in ids              # dynamic: enabled channel
    assert "channel-slack" not in ids            # disabled channel excluded


def test_research_is_brief_only_without_backend():
    # No searcher and no web_search backend -> empty findings, no crash.
    findings = ss.run_research(ss.build_research_brief(), searcher=None)
    # Either the default searcher is unavailable (-> []), or it runs; both fine.
    assert isinstance(findings, list)


def test_research_output_is_scrubbed():
    leaked = "here is sk-ant-AAAAAAAAAAAAAAAAAAAAAAAA and a result"

    def fake_searcher(query: str) -> str:
        return leaked

    topics = [ss.ResearchTopic("t", "q", "why")]
    findings = ss.run_research(topics, searcher=fake_searcher)
    assert len(findings) == 1
    assert "sk-ant-AAAAAAAAAAAAAAAAAAAAAAAA" not in findings[0]["summary"]
    assert "REDACTED" in findings[0]["summary"]


def test_research_survives_searcher_errors():
    def boom(query: str) -> str:
        raise RuntimeError("network down")

    findings = ss.run_research([ss.ResearchTopic("t", "q", "why")], searcher=boom)
    assert "search failed" in findings[0]["summary"]


# ---- report + audit --------------------------------------------------------

def test_run_audit_offline_is_ok():
    report = ss.run_audit(research=False)
    assert report.ok, [f.detail for f in report.failures]
    assert report.findings == []
    md = report.to_markdown()
    assert "Maverick security self-audit" in md
    assert "Invariants" in md
    assert "Research brief" in md


def test_run_audit_with_fake_searcher():
    report = ss.run_audit(research=True, searcher=lambda q: "no advisories found")
    assert report.findings, "expected findings from the injected searcher"
    assert all("summary" in f for f in report.findings)


def test_write_report(tmp_path):
    report = ss.run_audit(research=False)
    path = ss.write_report(report, directory=tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("# Maverick security self-audit")


def test_failing_invariant_marks_report_not_ok(monkeypatch):
    def broken():
        return ss.InvariantResult("x", "deliberately broken", False, "high", "boom")

    monkeypatch.setattr(ss, "INVARIANTS", (broken,))
    report = ss.run_audit(research=False)
    assert not report.ok
    assert report.failures and report.failures[0].id == "x"
