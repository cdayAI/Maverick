"""sonnet_tools SWE-bench baseline: the flat Sonnet+bash agent loop.

A fake ``anthropic`` module is injected via sys.modules so this runs with or
without the real SDK and never hits the network; the sandbox is a real tiny
git repo so the loop -> bash -> file edit -> ``git diff`` -> patch path is
exercised end to end. swe_bench is loaded by path (like the sibling tests).
"""
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path


def _load_swe_bench():
    if "swe_bench" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "swe_bench", Path(__file__).resolve().parent / "swe_bench.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["swe_bench"] = module
        spec.loader.exec_module(module)
    return sys.modules["swe_bench"]


_sb = _load_swe_bench()
run_sonnet_tools = _sb.run_sonnet_tools


# ---- fake Anthropic returning content blocks (text + tool_use) ----

class _Usage:
    input_tokens = 10
    output_tokens = 5


class _TextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, id, name, tool_input):
        self.id = id
        self.name = name
        self.input = tool_input


class _Resp:
    def __init__(self, content):
        self.content = content
        self.usage = _Usage()


def _fake_anthropic(scripted_turns):
    """scripted_turns: list of content-lists, one per messages.create() call."""
    seq = list(scripted_turns)
    state = {"i": 0}

    class _Messages:
        def create(self, **kwargs):
            content = seq[min(state["i"], len(seq) - 1)]
            state["i"] += 1
            return _Resp(content)

    class _Anthropic:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = _Anthropic
    return mod


def _git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    # Preserve PATH etc.; pin identity + ignore any global/system gitconfig so
    # the commit succeeds deterministically on any host.
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    }

    def g(*a):
        return subprocess.run(["git", "-C", str(repo), *a], check=True,
                              capture_output=True, text=True, env=env)

    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, env=env)
    (repo / "bug.py").write_text("def f():\n    return 1\n")
    g("add", "-A")
    g("commit", "-q", "-m", "init")
    base = g("rev-parse", "HEAD").stdout.strip()
    return repo, base


def test_sonnet_tools_runs_loop_and_extracts_diff(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    repo, base = _git_repo(tmp_path)

    from maverick.sandbox.local import LocalBackend
    # run_sonnet_tools does `from maverick.sandbox import build_sandbox` at call
    # time, so patch the name on that module.
    monkeypatch.setattr("maverick.sandbox.build_sandbox", lambda: LocalBackend(workdir=repo))
    monkeypatch.setitem(
        sys.modules, "anthropic",
        _fake_anthropic([
            # Turn 1: edit the file via bash.
            [_ToolUseBlock("tu_1", "bash", {"command": "printf '    return 42\\n' >> bug.py"})],
            # Turn 2: no tool_use -> loop ends.
            [_TextBlock("DONE")],
        ]),
    )

    row = run_sonnet_tools("inst-tools", "make f return 42", base_commit=base)

    assert row.pipeline == "sonnet_tools"
    assert row.outcome == "success"
    assert row.outcome != "not-implemented"
    # The predicted patch is the real git diff of the agent's edit.
    assert "bug.py" in row.predicted_patch
    assert "return 42" in row.predicted_patch
    # Two model calls were made (tool turn + final turn).
    assert row.tokens_in == 20
    assert row.tokens_out == 10


def test_sonnet_tools_no_edit_is_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("MAVERICK_BENCH_DRY_RUN", raising=False)
    repo, base = _git_repo(tmp_path)

    from maverick.sandbox.local import LocalBackend
    # run_sonnet_tools does `from maverick.sandbox import build_sandbox` at call
    # time, so patch the name on that module.
    monkeypatch.setattr("maverick.sandbox.build_sandbox", lambda: LocalBackend(workdir=repo))
    # Model answers immediately with no tool call -> no edits -> empty diff.
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic([[_TextBlock("DONE")]]))

    row = run_sonnet_tools("inst-noop", "do nothing", base_commit=base)
    assert row.outcome == "empty"
    assert row.predicted_patch == ""


def test_sonnet_tools_dry_run(monkeypatch):
    monkeypatch.setenv("MAVERICK_BENCH_DRY_RUN", "1")
    row = run_sonnet_tools("inst-dry", "brief")
    # dry-run must not touch Anthropic and is no longer "not-implemented".
    assert row.outcome != "not-implemented"
    assert row.pipeline == "sonnet_tools"
