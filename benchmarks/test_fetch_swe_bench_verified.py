"""Unit tests for the SWE-bench Verified fetch+stage helper.

Verifies the row→manifest conversion against the verified HF schema
(see https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_fetcher():
    p = Path(__file__).resolve().parent / "fetch_swe_bench_verified.py"
    spec = importlib.util.spec_from_file_location("bench_fetch", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bench_fetch"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestRowConversion:
    def _sample_hf_row(self):
        """Realistic shape — matches verified HF schema."""
        return {
            "instance_id": "django__django-12345",
            "repo": "django/django",
            "base_commit": "a" * 40,
            "patch": "diff --git a/x b/x\n@@\n-old\n+new\n",
            "test_patch": "diff --git a/tests/test_x.py b/tests/test_x.py\n@@\n-a\n+b\n",
            "problem_statement": "The Foo class breaks when bar is None",
            "hints_text": "comment: I think it's in models.py",
            "created_at": "2022-03-03T15:14:54Z",
            "version": "4.2",
            "environment_setup_commit": "b" * 40,
            "FAIL_TO_PASS": '["tests/test_x.py::TestFoo::test_bar_none"]',
            "PASS_TO_PASS": '["tests/test_x.py::TestFoo::test_normal", "tests/test_x.py::TestFoo::test_edge"]',
            "difficulty": "15 min - 1 hour",
        }

    def test_required_fields_extracted(self):
        m = _load_fetcher()
        out = m._row_to_manifest(self._sample_hf_row())
        assert out["instance_id"] == "django__django-12345"
        assert out["brief"] == "The Foo class breaks when bar is None"
        assert out["repo"] == "django/django"
        assert out["base_commit"] == "a" * 40
        assert out["language"] == "python"

    def test_fail_to_pass_parsed_from_json(self):
        """FAIL_TO_PASS arrives as a JSON-encoded string — must be
        decoded to a native list for the harness."""
        m = _load_fetcher()
        out = m._row_to_manifest(self._sample_hf_row())
        assert isinstance(out["fail_to_pass"], list)
        assert "tests/test_x.py::TestFoo::test_bar_none" in out["fail_to_pass"]

    def test_pass_to_pass_parsed_from_json(self):
        m = _load_fetcher()
        out = m._row_to_manifest(self._sample_hf_row())
        assert isinstance(out["pass_to_pass"], list)
        assert len(out["pass_to_pass"]) == 2

    def test_gold_patch_carried_through(self):
        """Required for defensive_validate's cheating detector after the
        hotfix wired MAVERICK_GOLD_PATCH from manifest → env."""
        m = _load_fetcher()
        out = m._row_to_manifest(self._sample_hf_row())
        assert "diff --git" in out["gold_patch"]
        assert "+new" in out["gold_patch"]

    def test_test_patch_NOT_exposed(self):
        """The grader's test_patch is the HOLDOUT; the agent must not
        see it. Our manifest must NOT include it."""
        m = _load_fetcher()
        out = m._row_to_manifest(self._sample_hf_row())
        assert "test_patch" not in out

    def test_handles_empty_test_lists(self):
        m = _load_fetcher()
        row = self._sample_hf_row()
        row["FAIL_TO_PASS"] = ""
        row["PASS_TO_PASS"] = None
        out = m._row_to_manifest(row)
        assert out["fail_to_pass"] == []
        assert out["pass_to_pass"] == []

    def test_handles_native_list_inputs(self):
        """Some HF loads (datasets library auto-decode) give native
        lists already."""
        m = _load_fetcher()
        row = self._sample_hf_row()
        row["FAIL_TO_PASS"] = ["test1", "test2"]
        out = m._row_to_manifest(row)
        assert out["fail_to_pass"] == ["test1", "test2"]

    def test_handles_malformed_json_gracefully(self):
        m = _load_fetcher()
        row = self._sample_hf_row()
        row["FAIL_TO_PASS"] = "this isn't json"
        out = m._row_to_manifest(row)
        # Falls back to empty list rather than raising.
        assert out["fail_to_pass"] == []


class TestManifestWrite:
    def test_writes_jsonl_one_per_line(self, tmp_path):
        import json
        m = _load_fetcher()
        rows = [
            {"instance_id": "a", "problem_statement": "p", "repo": "r/a",
             "base_commit": "x", "patch": "", "FAIL_TO_PASS": "[]",
             "PASS_TO_PASS": "[]"},
            {"instance_id": "b", "problem_statement": "q", "repo": "r/b",
             "base_commit": "y", "patch": "", "FAIL_TO_PASS": "[]",
             "PASS_TO_PASS": "[]"},
        ]
        out_path = tmp_path / "manifest.jsonl"
        n = m._write_manifest(rows, out_path)
        assert n == 2
        lines = out_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["instance_id"] == "a"
