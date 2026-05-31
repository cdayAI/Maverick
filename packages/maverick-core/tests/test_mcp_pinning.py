"""MCP tool-definition pinning: rug-pull / drift detection."""
from __future__ import annotations

from maverick import mcp_pinning as mp


def _spec(name, desc, schema=None):
    return {"name": name, "description": desc, "inputSchema": schema or {}}


# ---- fingerprint -----------------------------------------------------------

def test_fingerprint_stable_and_sensitive():
    a = mp.tool_fingerprint(_spec("t", "does X"))
    assert a == mp.tool_fingerprint(_spec("t", "does X"))           # stable
    assert a != mp.tool_fingerprint(_spec("t", "does X EVIL"))      # desc change
    assert a != mp.tool_fingerprint(_spec("t", "does X", {"a": 1})) # schema change


def test_fingerprint_ignores_key_order_in_schema():
    s1 = {"type": "object", "properties": {"a": {"type": "string"}}}
    s2 = {"properties": {"a": {"type": "string"}}, "type": "object"}
    assert mp.tool_fingerprint(_spec("t", "d", s1)) == mp.tool_fingerprint(_spec("t", "d", s2))


# ---- evaluate (pure diff) --------------------------------------------------

def test_evaluate_first_use_is_baseline():
    d = mp.evaluate(None, {"t": "h"}, mode="enforce")
    assert d.first_use and d.ok and d.allowed == {"t"}


def test_evaluate_match_is_ok():
    d = mp.evaluate({"t": "h"}, {"t": "h"}, mode="enforce")
    assert d.ok and d.allowed == {"t"}


def test_evaluate_enforce_withholds_drift_and_added():
    pinned = {"a": "h1", "b": "h2"}
    current = {"a": "h1", "b": "CHANGED", "c": "new"}
    d = mp.evaluate(pinned, current, mode="enforce")
    assert d.drifted == ["b"]
    assert d.added == ["c"]
    assert d.allowed == {"a"}            # only the unchanged tool survives
    assert not d.ok


def test_evaluate_warn_allows_but_reports():
    pinned = {"a": "h1"}
    current = {"a": "CHANGED"}
    d = mp.evaluate(pinned, current, mode="warn")
    assert d.drifted == ["a"]
    assert d.allowed == {"a"}            # warn registers it anyway
    assert not d.ok


def test_evaluate_off_allows_everything():
    d = mp.evaluate({"a": "h1"}, {"a": "CHANGED", "b": "new"}, mode="off")
    assert d.allowed == {"a", "b"} and d.ok


def test_evaluate_detects_removed():
    d = mp.evaluate({"a": "h", "b": "h"}, {"a": "h"}, mode="warn")
    assert d.removed == ["b"]


# ---- reconcile (TOFU + persistence) ----------------------------------------

def test_reconcile_tofu_then_detects_drift(tmp_path):
    pins = tmp_path / "pins.json"
    tools = [_spec("t", "v1")]
    # first use -> baseline recorded
    d1 = mp.reconcile("srv", tools, mode="enforce", path=pins)
    assert d1.first_use and pins.exists()
    # same tools -> ok
    d2 = mp.reconcile("srv", tools, mode="enforce", path=pins)
    assert d2.ok and "t" in d2.allowed
    # changed tool -> drift, withheld under enforce
    d3 = mp.reconcile("srv", [_spec("t", "v2-rugpull")], mode="enforce", path=pins)
    assert "t" in d3.drifted and "t" not in d3.allowed


def test_reconcile_off_does_not_write(tmp_path):
    pins = tmp_path / "pins.json"
    mp.reconcile("srv", [_spec("t", "v1")], mode="off", path=pins)
    assert not pins.exists()


def test_repin_clears(tmp_path):
    pins = tmp_path / "pins.json"
    mp.reconcile("a", [_spec("t", "v1")], mode="enforce", path=pins)
    mp.reconcile("b", [_spec("t", "v1")], mode="enforce", path=pins)
    assert mp.repin("a", path=pins) == 1
    assert "a" not in mp.load_pins(pins) and "b" in mp.load_pins(pins)
    assert mp.repin(path=pins) == 1      # clears the remaining one


# ---- integration: tools_from_mcp honours the decision ----------------------

class _FakeClient:
    def __init__(self, name, tools):
        self.spec = type("S", (), {"name": name})()
        self.tools = tools

    async def call_tool(self, *a, **k):  # pragma: no cover - not invoked
        return "ok"


def test_tools_from_mcp_enforce_withholds_drifted(tmp_path, monkeypatch):
    import maverick.config as config
    from maverick import mcp_tools
    pins = tmp_path / "pins.json"
    monkeypatch.setattr(
        config, "get_mcp",
        lambda: {"tool_pinning": "enforce", "pins_path": str(pins)},
    )
    c1 = _FakeClient("srv", [_spec("alpha", "v1"), _spec("beta", "v1")])
    # First use pins both -> both register.
    names1 = {t.name for t in mcp_tools.tools_from_mcp(c1)}
    assert names1 == {"mcp_srv__alpha", "mcp_srv__beta"}
    # beta rug-pulled -> withheld; alpha unchanged -> survives.
    c2 = _FakeClient("srv", [_spec("alpha", "v1"), _spec("beta", "v2-evil")])
    names2 = {t.name for t in mcp_tools.tools_from_mcp(c2)}
    assert names2 == {"mcp_srv__alpha"}


def test_tools_from_mcp_warn_keeps_but_flags(tmp_path, monkeypatch):
    import maverick.config as config
    from maverick import mcp_tools
    pins = tmp_path / "pins.json"
    monkeypatch.setattr(
        config, "get_mcp",
        lambda: {"tool_pinning": "warn", "pins_path": str(pins)},
    )
    c1 = _FakeClient("srv", [_spec("alpha", "v1")])
    mcp_tools.tools_from_mcp(c1)
    c2 = _FakeClient("srv", [_spec("alpha", "v2")])
    names = {t.name for t in mcp_tools.tools_from_mcp(c2)}
    assert names == {"mcp_srv__alpha"}   # warn still registers
