from __future__ import annotations

import asyncio
import types


def test_handle_message_blocks_unauthorized_user(tmp_path):
    from maverick.server import Server
    from maverick.world_model import WorldModel
    from maverick.llm import LLM

    server = Server(world=WorldModel(), llm=LLM(), workdir=tmp_path)
    server.set_allowed_users("telegram", {"allowed-user"})

    msg = types.SimpleNamespace(
        channel="telegram",
        user_id="attacker-user",
        text="run shell command",
    )

    out = asyncio.run(server._handle_message(msg))

    assert out == "⚠ Unauthorized user."
    assert len(server.world.list_goals()) == 0
