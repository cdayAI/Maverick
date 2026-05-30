"""preview_diff must not diff files outside the sandbox workspace.

Regression: agent-supplied `paths` were appended to `git diff -- <path>`
with no containment, so `["../../etc/shadow"]` (or an absolute path) made
git read an out-of-tree file and return its contents to the agent. Paths
are now resolved and required to stay within the workdir. The check runs
before git is invoked, so these tests don't need git installed.
"""
from pathlib import Path

from maverick.sandbox import LocalBackend
from maverick.tools.preview_diff import preview_diff


def test_rejects_relative_traversal(tmp_path: Path):
    tool = preview_diff(LocalBackend(workdir=tmp_path))
    out = tool.fn({"paths": ["../../etc/passwd"]})
    assert "escapes the workspace" in out


def test_rejects_absolute_outside_path(tmp_path: Path):
    tool = preview_diff(LocalBackend(workdir=tmp_path))
    out = tool.fn({"paths": ["/etc/passwd"]})
    assert "escapes the workspace" in out


def test_in_workspace_path_passes_containment(tmp_path: Path):
    # An in-tree path clears containment; without a .git dir the tool then
    # returns the not-a-repo message (NOT the traversal error).
    (tmp_path / "src").mkdir()
    tool = preview_diff(LocalBackend(workdir=tmp_path))
    out = tool.fn({"paths": ["src/app.py"]})
    assert "escapes the workspace" not in out
    assert "not a git repo" in out
