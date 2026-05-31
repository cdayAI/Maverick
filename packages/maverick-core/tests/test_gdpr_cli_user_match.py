"""GDPR export-user / erase must reach CLI `chat` conversations.

`chat` scopes each REPL session to a unique ``local:<uuid>`` user_id, so an
exact match on the documented ``--user local`` found nothing -- a user could
never export (Art. 15) or erase (Art. 17) their own CLI chat history.
``_conversation_user_matches`` now also matches the colon-scoped family.
"""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from maverick.cli import _conversation_user_matches, main
from maverick.world_model import open_world


def test_user_match_predicate():
    assert _conversation_user_matches("local:abc123", "local") is True
    assert _conversation_user_matches("local", "local") is True
    assert _conversation_user_matches("12345", "12345") is True
    # No colon boundary -> not a prefix match (don't over-match 12345 vs 1234).
    assert _conversation_user_matches("123456", "12345") is False
    assert _conversation_user_matches("other:x", "local") is False


def test_export_and_erase_reach_cli_chat_sessions(tmp_path: Path):
    db = tmp_path / "world.db"
    w = open_world(db)
    c1 = w.get_or_create_conversation("cli", "local:aaa")
    c2 = w.get_or_create_conversation("cli", "local:bbb")
    other = w.get_or_create_conversation("telegram", "999")
    w.append_turn(c1.id, "user", "secret-session-one")
    w.append_turn(c2.id, "user", "secret-session-two")
    w.append_turn(other.id, "user", "unrelated-telegram")

    runner = CliRunner()
    exp = runner.invoke(main, ["--db", str(db), "export-user", "--channel", "cli", "--user", "local"])
    assert exp.exit_code == 0
    assert "secret-session-one" in exp.output
    assert "secret-session-two" in exp.output
    assert "unrelated-telegram" not in exp.output  # scoped to the cli channel

    er = runner.invoke(main, ["--db", str(db), "erase", "--channel", "cli", "--user", "local", "--yes"])
    assert er.exit_code == 0

    after = runner.invoke(main, ["--db", str(db), "export-user", "--channel", "cli", "--user", "local"])
    assert "secret-session-one" not in after.output
    assert "secret-session-two" not in after.output
    # The unrelated telegram conversation is untouched.
    assert w.get_or_create_conversation("telegram", "999").id == other.id
