"""Persona tests."""
from __future__ import annotations

import tempfile
from pathlib import Path

from maverick.persona import STYLES, load_persona, render_persona_prompt


def test_no_config_returns_empty(monkeypatch):
    monkeypatch.setenv("MAVERICK_CONFIG", "/nonexistent/path.toml")
    p = load_persona()
    assert p == {"name": "", "style": "", "addendum": ""}
    assert render_persona_prompt() == ""


def test_full_persona(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(
            '[persona]\n'
            'name = "Atlas"\n'
            'style = "concise"\n'
            'addendum = "Always cite sources with URLs."\n'
        )
        path = Path(f.name)
    try:
        monkeypatch.setenv("MAVERICK_CONFIG", str(path))
        prompt = render_persona_prompt()
        assert "Atlas" in prompt
        assert STYLES["concise"] in prompt
        assert "cite sources" in prompt
        assert prompt.startswith("\n\n# Persona\n\n")
    finally:
        path.unlink()


def test_partial_persona_name_only(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[persona]\nname = "Maverick"\n')
        path = Path(f.name)
    try:
        monkeypatch.setenv("MAVERICK_CONFIG", str(path))
        prompt = render_persona_prompt()
        assert "Maverick" in prompt
        # No style or addendum content.
        for s in STYLES.values():
            assert s not in prompt
    finally:
        path.unlink()


def test_unknown_style_skipped(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[persona]\nname = "X"\nstyle = "made-up-style"\n')
        path = Path(f.name)
    try:
        monkeypatch.setenv("MAVERICK_CONFIG", str(path))
        prompt = render_persona_prompt()
        # Name still present; unknown style silently dropped.
        assert "X" in prompt
    finally:
        path.unlink()
