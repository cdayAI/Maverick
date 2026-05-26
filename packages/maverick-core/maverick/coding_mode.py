"""Coding-mode prompts + patch validation for benchmark-grade output.

SWE-bench Pro (and the upstream evaluator) expects ONE unified diff,
not prose. Our default WORKER_SYSTEM_TEMPLATE produces prose-with-
diff which scores zero. This module ships:

  - CODER_CODING_MODE_TEMPLATE: replacement system prompt that
    enforces diff-only FINAL.
  - validate_patch(patch, workdir): runs `git apply --check` so the
    agent learns from a bad patch BEFORE submitting it.
  - extract_unified_diff(text): pulls the first valid diff out of an
    LLM reply (handles markdown fences + leading prose).
  - run_failing_tests(workdir, fail_to_pass, pass_to_pass, sandbox):
    test-driven verifier replacement for SWE-bench-style briefs.
    Returns a structured result the orchestrator uses instead of /
    alongside the LLM verifier.

The `--coding-mode` CLI flag (or [coding] mode=true config) wires
these in; default OFF so the consumer-facing kernel stays focused on
prose tasks.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


CODER_CODING_MODE_TEMPLATE = """You are a coding agent solving a software engineering task.

Your role: {role}
Your depth: {depth} (root = 0, max = {max_depth})

OUTPUT FORMAT (STRICT):
When you have a fix ready, respond with EXACTLY this format:

FINAL:
```diff
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -10,3 +10,3 @@
-old line
+new line
```

Rules:
1. ONE unified diff per FINAL. No prose explanation, no preamble,
   no markdown headers, no "I think" / "let me explain".
2. The diff MUST apply cleanly to HEAD via `git apply`. If you're
   unsure, run `read_file` to verify the exact line content before
   composing the diff.
3. Use `shell` to run tests + `git apply --check` before declaring
   FINAL. The orchestrator validates your patch and will reject
   if it doesn't apply.
4. Prefer the SMALLEST diff that makes the failing tests pass.
   Drive-by formatting changes will get the patch rejected.
5. If you need information, use `read_file` / `list_dir` / `shell`
   freely. Tool budget is not the bottleneck; correctness is.
6. The `spawn_subagent` and `spawn_swarm` tools are available for
   sub-tasks (e.g., "research how the test fixture is set up");
   they cannot themselves produce FINAL.

Available tools include file ops, shell (sandboxed), spawn_subagent,
spawn_swarm. End with `FINAL:` followed by the diff block."""


# A valid unified diff starts with `--- a/...` followed by `+++ b/...`
# followed by at least one `@@ ` hunk header. Anything else is prose
# that happens to contain triple-dash and gets rejected.
_VALID_DIFF_HEADER = re.compile(
    r"---\s+(?:a/)?\S.*?\n\+\+\+\s+(?:b/)?\S.*?\n@@\s",
    re.DOTALL,
)
_DIFF_FILE_START = re.compile(r"(?:^|\n)(---\s+(?:a/)?\S)", re.DOTALL)


def extract_unified_diff(text: str) -> Optional[str]:
    """Extract the unified diff from an LLM reply, or None.

    Wave 9 rewrite (council code reviewer #4 + #5): the prior version
    accepted any text containing `--- a/` and lost content after a
    backtick (Markdown patches break). New approach:

      1. Strip the `FINAL:` prefix.
      2. Strip ALL markdown ``` fences (open + close).
      3. Find every position where a file header starts (`--- a/`)
         and a valid `+++ b/...` + `@@` follows. If none, return None.
      4. Take from the first valid header to end-of-string.

    Crucially: returns None on no-valid-diff so callers can hard-reject
    rather than the previous `patch = extract(text) or text` fallback
    that fed PROSE into `git apply --check` and inflated apply-rate
    variance (council code reviewer #5 / #3).
    """
    if not text:
        return None
    work = text
    final_idx = work.find("FINAL:")
    if final_idx >= 0:
        work = work[final_idx + len("FINAL:"):]

    # Strip ALL fence markers globally so multi-fenced diffs are
    # reconstructed correctly. Patches to Markdown files that contain
    # literal ``` inside their hunks survive because of \n on either
    # side of the close fence in the LLM's output: we strip the lone
    # ``` lines, not inline backticks.
    cleaned_lines = []
    for line in work.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    # Find the first file header that's followed by a valid +++/@@ pair.
    m = _VALID_DIFF_HEADER.search(cleaned)
    if not m:
        return None
    diff = cleaned[m.start():]
    return diff.rstrip() + "\n"


@dataclass
class PatchValidation:
    valid: bool
    reason: str = ""
    git_apply_stderr: str = ""


def validate_patch(patch: str, workdir: Path) -> PatchValidation:
    """Run `git apply --check` to confirm the patch applies cleanly.

    The agent uses this BEFORE declaring FINAL. A failing check
    triggers a revision pass with the git_apply_stderr fed back as
    the critique.
    """
    if not patch or not patch.strip():
        return PatchValidation(valid=False, reason="empty patch")
    if "--- a/" not in patch or "+++ b/" not in patch:
        return PatchValidation(
            valid=False,
            reason="patch is missing `--- a/...` / `+++ b/...` headers",
        )
    if not (workdir / ".git").exists():
        return PatchValidation(
            valid=False,
            reason="workdir is not a git repository; cannot validate",
        )
    try:
        proc = subprocess.run(
            ["git", "-C", str(workdir), "apply", "--check", "-"],
            input=patch.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return PatchValidation(
            valid=False,
            reason="git apply --check timed out",
        )
    if proc.returncode == 0:
        return PatchValidation(valid=True)
    return PatchValidation(
        valid=False,
        reason="git apply --check rejected the patch",
        git_apply_stderr=proc.stderr.decode("utf-8", errors="replace")[:2000],
    )


@dataclass
class TestRunResult:
    fail_to_pass_passing: int = 0
    fail_to_pass_total: int = 0
    pass_to_pass_passing: int = 0
    pass_to_pass_total: int = 0
    error: str = ""
    raw_output: str = ""
    runner: str = ""
    skipped: bool = False  # True when language/runner unsupported

    @property
    def all_pass(self) -> bool:
        return (
            self.fail_to_pass_passing == self.fail_to_pass_total
            and self.pass_to_pass_passing == self.pass_to_pass_total
            and not self.error
        )

    @property
    def score(self) -> float:
        """Combined score: did we fix the failing tests AND not break passing ones?

        Returns in [0, 1]. 1.0 = perfect resolution.
        """
        if self.error:
            return 0.0
        total = self.fail_to_pass_total + self.pass_to_pass_total
        if total == 0:
            return 0.0
        passing = self.fail_to_pass_passing + self.pass_to_pass_passing
        return passing / total

    def summary(self) -> str:
        if self.error:
            return f"test runner error: {self.error}"
        return (
            f"FAIL_TO_PASS: {self.fail_to_pass_passing}/{self.fail_to_pass_total} pass; "
            f"PASS_TO_PASS: {self.pass_to_pass_passing}/{self.pass_to_pass_total} pass"
        )


# ---- Polyglot test runners (Wave 9, council multi-lang agent) ----------

_RUNNER_MARKERS = [
    ("pytest",  ("pyproject.toml", "setup.py", "setup.cfg", "tox.ini")),
    ("node",    ("package.json",)),
    ("cargo",   ("Cargo.toml",)),
    ("gotest",  ("go.mod",)),
    ("rspec",   ("Gemfile",)),
    ("gradle",  ("build.gradle", "build.gradle.kts", "settings.gradle")),
    ("maven",   ("pom.xml",)),
]


def detect_test_runner(workdir: Path) -> str:
    """Return one of: pytest|jest|vitest|mocha|cargo|gotest|rspec|gradle|maven|unsupported."""
    import json as _json
    for name, files in _RUNNER_MARKERS:
        if not any((workdir / f).exists() for f in files):
            continue
        if name == "node":
            try:
                pkg = _json.loads((workdir / "package.json").read_text())
                test_script = (pkg.get("scripts") or {}).get("test", "").lower()
                if "vitest" in test_script:
                    return "vitest"
                if "mocha" in test_script:
                    return "mocha"
                return "jest"
            except Exception:
                return "jest"
        return name
    return "unsupported"


def _cmd_for(runner: str, ids: list[str]):
    """Return shell command string OR list-of-strings (cargo runs per-id)."""
    def q(s: str) -> str:
        return "'" + s.replace("'", "'\"'\"'") + "'"
    if runner == "pytest":
        # Wave 9 fix (council #12): NO `-x` — that aborts on first
        # failure and we can never count PASS_TO_PASS correctly.
        return "pytest --tb=short -p no:cacheprovider " + " ".join(q(i) for i in ids)
    if runner in ("jest", "vitest"):
        files: list[str] = []
        names: list[str] = []
        for i in ids:
            if "::" in i:
                f, n = i.rsplit("::", 1)
                files.append(f)
                names.append(n)
            else:
                files.append(i)
                names.append(".*")
        pat = "|".join(re.escape(n) for n in names) or ".*"
        cmd_name = "jest" if runner == "jest" else "vitest run --reporter=basic"
        return f"npx --no-install {cmd_name} --colors=false -t {q(pat)} " + " ".join(q(f) for f in files)
    if runner == "mocha":
        return "npx --no-install mocha --reporter=spec " + " ".join(q(i) for i in ids)
    if runner == "cargo":
        return ["cargo test --no-fail-fast " + q(i) + " -- --exact --nocapture" for i in ids]
    if runner == "gotest":
        pkgs = sorted({i.split("::", 1)[0] for i in ids if "::" in i})
        names = "|".join(re.escape(i.split("::", 1)[1]) for i in ids if "::" in i)
        if not names:
            names = "."
        return f"go test -count=1 -run '^({names})$' " + " ".join(pkgs or ["./..."])
    if runner == "rspec":
        return "bundle exec rspec --format documentation " + " ".join(q(i) for i in ids)
    if runner == "gradle":
        return "./gradlew test --no-daemon " + " ".join(f"--tests {q(i)}" for i in ids)
    if runner == "maven":
        return f"mvn -B -q test -Dtest={q(','.join(ids))}"
    return None


# Each parser: (passed, failed_or_errored, parsed_ok).
def _parse_pytest(out: str) -> tuple[int, int, bool]:
    # Wave 9 (council B7): anchor to the summary line `===== ... in Ns =====`,
    # not the first occurrence of "N passed" which can match stdout from
    # tests that emit "3 passed" in their own output.
    m = re.search(
        r"=+\s*"
        r"(?:(?P<failed>\d+)\s+failed,?\s*)?"
        r"(?:(?P<errored>\d+)\s+error[s]?,?\s*)?"
        r"(?:(?P<passed>\d+)\s+passed,?\s*)?"
        r"(?:.*?in\s+[\d.]+\s*s)",
        out, re.IGNORECASE,
    )
    if not m:
        # Fall back to the last "passed/failed/error" tokens in the
        # output — better than the prior first-match behavior.
        m_pass = list(re.finditer(r"(\d+)\s+passed", out))
        m_fail = list(re.finditer(r"(\d+)\s+failed", out))
        m_err = list(re.finditer(r"(\d+)\s+error[s]?", out))
        if not (m_pass or m_fail or m_err):
            return 0, 0, False
        p = int(m_pass[-1].group(1)) if m_pass else 0
        f = int(m_fail[-1].group(1)) if m_fail else 0
        e = int(m_err[-1].group(1)) if m_err else 0
        return p, f + e, True
    p = int(m.group("passed") or 0)
    f = int(m.group("failed") or 0)
    e = int(m.group("errored") or 0)
    return p, f + e, True


def _parse_jest(out: str) -> tuple[int, int, bool]:
    m = re.search(
        r"Tests:\s+(?:(?P<failed>\d+)\s+failed,\s*)?"
        r"(?:(?P<skipped>\d+)\s+skipped,\s*)?"
        r"(?:(?P<passed>\d+)\s+passed,\s*)?"
        r"(?P<total>\d+)\s+total",
        out,
    )
    if not m:
        return 0, 0, False
    return int(m.group("passed") or 0), int(m.group("failed") or 0), True


def _parse_cargo(out: str) -> tuple[int, int, bool]:
    m = re.search(r"test result:.*?(\d+)\s+passed;\s*(\d+)\s+failed", out)
    return (int(m.group(1)), int(m.group(2)), True) if m else (0, 0, False)


def _parse_gotest(out: str) -> tuple[int, int, bool]:
    p = len(re.findall(r"^--- PASS:", out, re.M))
    f = len(re.findall(r"^--- FAIL:", out, re.M))
    ok = ("PASS" in out) or ("FAIL" in out) or ("ok  " in out)
    return p, f, ok


def _parse_rspec(out: str) -> tuple[int, int, bool]:
    m = re.search(r"(\d+)\s+examples?,\s*(\d+)\s+failures?", out)
    if not m:
        return 0, 0, False
    total = int(m.group(1))
    failed = int(m.group(2))
    return total - failed, failed, True


def _parse_gradle(out: str) -> tuple[int, int, bool]:
    p = len(re.findall(r"\bPASSED\b", out))
    f = len(re.findall(r"\bFAILED\b", out))
    ok = ("BUILD SUCCESSFUL" in out) or ("BUILD FAILED" in out)
    return p, f, ok


def _parse_maven(out: str) -> tuple[int, int, bool]:
    m = re.search(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)", out)
    if not m:
        return 0, 0, False
    return (
        int(m.group(1)) - int(m.group(2)) - int(m.group(3)),
        int(m.group(2)) + int(m.group(3)),
        True,
    )


_PARSERS = {
    "pytest": _parse_pytest,
    "jest":   _parse_jest,
    "vitest": _parse_jest,
    "mocha":  _parse_jest,
    "cargo":  _parse_cargo,
    "gotest": _parse_gotest,
    "rspec":  _parse_rspec,
    "gradle": _parse_gradle,
    "maven":  _parse_maven,
}


def run_failing_tests(
    workdir: Path,
    fail_to_pass: list[str],
    pass_to_pass: list[str],
    sandbox,
    *,
    timeout: float = 600.0,
) -> TestRunResult:
    """Apply the staged patch + run the SWE-bench tests.

    Wave 9: polyglot dispatch on detected runner (pytest / jest /
    cargo / gotest / rspec / gradle / maven). Unsupported runners
    return TestRunResult(skipped=True) so the caller can skip the
    instance instead of scoring 0.
    """
    if not fail_to_pass and not pass_to_pass:
        return TestRunResult(error="no FAIL_TO_PASS or PASS_TO_PASS tests provided")

    runner = detect_test_runner(workdir)
    if runner == "unsupported":
        return TestRunResult(
            error=f"unsupported test runner for workdir={workdir}",
            skipped=True, runner=runner,
        )

    parse = _PARSERS.get(runner)
    if parse is None:
        return TestRunResult(
            error=f"no parser for runner {runner!r}",
            skipped=True, runner=runner,
        )

    result = TestRunResult(
        fail_to_pass_total=len(fail_to_pass),
        pass_to_pass_total=len(pass_to_pass),
        runner=runner,
    )

    def _run(test_ids: list[str]) -> tuple[int, int, str]:
        if not test_ids:
            return 0, 0, ""
        cmd = _cmd_for(runner, test_ids)
        cmds = cmd if isinstance(cmd, list) else [cmd]
        passed = failed = 0
        chunks: list[str] = []
        for c in cmds:
            try:
                r = sandbox.exec(c)
            except Exception as e:  # pragma: no cover
                return passed, len(test_ids) - passed, f"sandbox exec failed: {e}"
            out = (r.stdout or "") + "\n" + (r.stderr or "")
            p, f, ok = parse(out)
            # Wave 9 fix (council #13): keep the END of the output so we
            # capture the summary line, not the session header.
            chunks.append(out[-1000:])
            if not ok:
                # Parser saw nothing in summary; treat remaining as failed.
                return passed, failed + (len(test_ids) - passed - failed), "\n".join(chunks)
            passed += p
            failed += f
        return passed, failed, "\n".join(chunks)

    f_pass, _, f_out = _run(fail_to_pass)
    result.fail_to_pass_passing = f_pass
    p_pass, _, p_out = _run(pass_to_pass)
    result.pass_to_pass_passing = p_pass
    result.raw_output = (f_out + "\n" + p_out)[-2000:]
    return result


@dataclass
class CodingModeConfig:
    """Settings for benchmark / coding tasks."""
    enabled: bool = False
    best_of_n: int = 1
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    require_apply_check: bool = True


def from_env() -> CodingModeConfig:
    """Read coding-mode config from env (set by the SWE-bench harness)."""
    import os
    cfg = CodingModeConfig()
    cfg.enabled = os.environ.get("MAVERICK_CODING_MODE", "").lower() in ("1", "true", "yes")
    try:
        cfg.best_of_n = int(os.environ.get("MAVERICK_BEST_OF_N", "1"))
    except ValueError:
        cfg.best_of_n = 1
    cfg.fail_to_pass = [
        t for t in os.environ.get("MAVERICK_FAIL_TO_PASS", "").split("||") if t
    ]
    cfg.pass_to_pass = [
        t for t in os.environ.get("MAVERICK_PASS_TO_PASS", "").split("||") if t
    ]
    return cfg


@dataclass
class Candidate:
    """One of N candidate patches considered during best-of-N selection."""
    index: int
    patch: str
    score: float
    apply_check_passed: bool
    test_result: Optional["TestRunResult"] = None
    error: str = ""


def select_best_candidate(candidates: list[Candidate]) -> Optional[Candidate]:
    """Pick the candidate with the highest test score; tiebreak on
    apply-check + smaller patch (Occam).

    Used at the end of a best-of-N orchestrator run. Returns None if
    no candidate is usable.
    """
    if not candidates:
        return None
    usable = [c for c in candidates if c.apply_check_passed and not c.error]
    if not usable:
        # Fall back to whatever applies.
        usable = [c for c in candidates if c.apply_check_passed]
    if not usable:
        # Last resort: anything non-empty.
        usable = [c for c in candidates if c.patch.strip()]
    if not usable:
        return None
    # Higher score first; smaller patch wins ties.
    usable.sort(key=lambda c: (-c.score, len(c.patch)))
    return usable[0]


async def evaluate_candidate(
    patch: str,
    workdir: Path,
    cfg: CodingModeConfig,
    sandbox,
    index: int,
) -> Candidate:
    """Validate + score one candidate.

    Wave 9 rewrite (council code reviewer #7 + #8): the prior stash
    dance was unsafe (silent no-op on clean tree, stash pop popped
    prior candidate's stash, untracked files leaked between
    candidates, apply return code ignored). New approach: spawn a
    git worktree per candidate at a side-path, run everything there.
    Real isolation. Falls back to in-place + reset --hard HEAD if
    worktree creation fails (e.g. read-only workdir).
    """
    cand = Candidate(index=index, patch=patch, score=0.0,
                     apply_check_passed=False)
    if not patch or not patch.strip():
        cand.error = "empty patch"
        return cand

    validation = validate_patch(patch, workdir)
    cand.apply_check_passed = validation.valid
    if not validation.valid:
        cand.error = validation.reason
        return cand

    if not (cfg.fail_to_pass or cfg.pass_to_pass):
        # No ground-truth tests; score by apply-check (smaller diff
        # tie-break happens in select_best_candidate).
        cand.score = 0.5
        return cand

    import subprocess as _subprocess
    import tempfile as _tempfile
    import shutil as _shutil

    wt_root = Path(_tempfile.mkdtemp(prefix=f"maverick-cand-{index}-"))
    wt_path = wt_root / "wt"

    # Prefer git worktree (true isolation, branches independently).
    used_worktree = False
    try:
        proc = _subprocess.run(
            ["git", "-C", str(workdir), "worktree", "add",
             "--detach", str(wt_path), "HEAD"],
            capture_output=True, timeout=60,
        )
        used_worktree = (proc.returncode == 0)
    except Exception:
        used_worktree = False

    eval_dir = wt_path if used_worktree else workdir

    try:
        ap = _subprocess.run(
            ["git", "-C", str(eval_dir), "apply", "-"],
            input=patch.encode("utf-8"),
            capture_output=True, timeout=30,
        )
        if ap.returncode != 0:
            cand.error = (
                "patch validated by --check but failed real apply: "
                + (ap.stderr or b"").decode("utf-8", errors="replace")[:500]
            )
            cand.apply_check_passed = False
            return cand
        # Point the sandbox at the worktree for the test run. Best-effort:
        # if sandbox doesn't expose workdir we skip the swap (tests run
        # in original workdir, which is OK when used_worktree=False).
        original_workdir = getattr(sandbox, "workdir", None)
        if used_worktree and original_workdir is not None:
            try:
                sandbox.workdir = eval_dir
            except Exception:
                pass
        try:
            test_result = run_failing_tests(
                eval_dir, cfg.fail_to_pass, cfg.pass_to_pass, sandbox,
            )
        finally:
            if used_worktree and original_workdir is not None:
                try:
                    sandbox.workdir = original_workdir
                except Exception:
                    pass

        cand.test_result = test_result
        cand.score = test_result.score
    finally:
        # Clean up the worktree (NEVER the original workdir).
        if used_worktree:
            try:
                _subprocess.run(
                    ["git", "-C", str(workdir), "worktree", "remove",
                     "--force", str(wt_path)],
                    capture_output=True, timeout=30,
                )
            except Exception:
                pass
            try:
                _shutil.rmtree(wt_root, ignore_errors=True)
            except Exception:
                pass
        else:
            # Fallback path: best-effort reset.
            try:
                _subprocess.run(
                    ["git", "-C", str(workdir), "reset", "--hard", "HEAD"],
                    capture_output=True, timeout=20,
                )
                _subprocess.run(
                    ["git", "-C", str(workdir), "clean", "-fd"],
                    capture_output=True, timeout=20,
                )
            except Exception:
                pass
    return cand
