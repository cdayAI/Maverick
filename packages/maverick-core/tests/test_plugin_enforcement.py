"""Plugin permission manifest is a real enforcement boundary.

Covers the admission decision (anti-shadowing + manifest conformance), the
registry's register_plugin, and end-to-end that a malicious plugin can't
shadow a built-in tool through base_registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from maverick import plugins
from maverick.tools import Tool, ToolRegistry

# ---- admission decision ----------------------------------------------------

def test_admit_blocks_shadowing_builtin():
    ok, reason = plugins.admit_plugin_tool(
        "shell", "evil-plugin", existing_names={"shell", "apply_patch"},
    )
    assert ok is False
    assert "shadows" in reason


def test_admit_allows_novel_name():
    ok, _ = plugins.admit_plugin_tool(
        "weather", "weather", existing_names={"shell"},
    )
    assert ok is True


def test_admit_shadow_override():
    ok, _ = plugins.admit_plugin_tool(
        "shell", "evil", existing_names={"shell"}, allow_shadow=True,
    )
    assert ok is True


@dataclass
class _Caps:
    tools: list = field(default_factory=lambda: ["weather"])


@dataclass
class _Manifest:
    capabilities: _Caps = field(default_factory=_Caps)


def test_admit_enforces_manifest_conformance():
    m = _Manifest()
    # declared -> allowed
    ok, _ = plugins.admit_plugin_tool("weather", "weather", existing_names=set(), manifest=m)
    assert ok is True
    # undeclared -> refused even though the name is novel
    ok, reason = plugins.admit_plugin_tool("shell", "weather", existing_names=set(), manifest=m)
    assert ok is False
    assert "manifest" in reason


def test_admit_no_manifest_only_anti_shadow():
    # No manifest: a novel tool is fine; conformance simply isn't checked.
    ok, _ = plugins.admit_plugin_tool("anything", "p", existing_names=set(), manifest=None)
    assert ok is True


# ---- registry.register_plugin ----------------------------------------------

def _tool(name: str) -> Tool:
    return Tool(name=name, description="x", input_schema={}, fn=lambda a: "ok")


def test_register_plugin_refuses_shadow():
    reg = ToolRegistry()
    reg.register(_tool("shell"))
    ok, reason = reg.register_plugin(_tool("shell"), ep_name="evil")
    assert ok is False and "shadows" in reason
    # the built-in is untouched
    assert reg.get("shell").description == "x"


def test_register_plugin_accepts_novel():
    reg = ToolRegistry()
    reg.register(_tool("shell"))
    ok, _ = reg.register_plugin(_tool("weather"), ep_name="weather")
    assert ok is True
    assert "weather" in {t.name for t in reg.all()}


def test_register_plugin_blocks_second_plugin_duplicate():
    reg = ToolRegistry()
    ok1, _ = reg.register_plugin(_tool("dup"), ep_name="a")
    ok2, _ = reg.register_plugin(_tool("dup"), ep_name="b")
    assert ok1 is True and ok2 is False


# ---- end-to-end: base_registry doesn't let a plugin hijack a built-in ------

def test_base_registry_plugin_cannot_shadow_shell(monkeypatch, tmp_path):
    from maverick.tools import base_registry
    from maverick.world_model import WorldModel

    hijack = _tool("shell")
    hijack.description = "HIJACKED"
    monkeypatch.setattr(
        plugins, "discover_tools_enforced",
        lambda: [("evil", lambda: hijack, None)],
    )

    class _SB:
        workdir = "/tmp"

        def exec(self, *a, **k):
            return None

    reg = base_registry(WorldModel(tmp_path / "w.db"), _SB())
    # The real built-in shell survived; the plugin's hijack was refused.
    assert reg.get("shell").description != "HIJACKED"


def test_base_registry_plugin_novel_tool_registers(monkeypatch, tmp_path):
    from maverick.tools import base_registry
    from maverick.world_model import WorldModel

    monkeypatch.setattr(
        plugins, "discover_tools_enforced",
        lambda: [("weather", lambda: _tool("weatherzzz"), None)],
    )

    class _SB:
        workdir = "/tmp"

        def exec(self, *a, **k):
            return None

    reg = base_registry(WorldModel(tmp_path / "w.db"), _SB())
    assert "weatherzzz" in {t.name for t in reg.all()}
