"""Channel interface.

Normalize every platform (CLI, Telegram, iMessage, ...) to the same shape
so the agent loop doesn't have to care where a message came from.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Awaitable, Callable


def _max_inbound_chars() -> int:
    """Cap on inbound text fed to the swarm. A single oversized inbound
    message (a 200KB email, an attacker-crafted mention) would otherwise
    drive an uncapped-context, uncapped-cost agent run. Override with
    MAVERICK_MAX_INBOUND_CHARS; 0 disables the cap."""
    try:
        return int(os.environ.get("MAVERICK_MAX_INBOUND_CHARS", "100000"))
    except ValueError:
        return 100000


@dataclass
class IncomingMessage:
    user_id: str
    text: str
    attachments: list[dict] = field(default_factory=list)
    channel: str = ""
    raw: object = None

    def __post_init__(self) -> None:
        cap = _max_inbound_chars()
        if cap and isinstance(self.text, str) and len(self.text) > cap:
            self.text = self.text[:cap] + "\n\n[...truncated by Maverick inbound cap]"


Handler = Callable[[IncomingMessage], Awaitable[str]]
"""A handler takes a normalized message and returns the agent's reply."""


class Channel(ABC):
    """Abstract channel adapter.

    Lifecycle:
      - ``start()`` blocks (or runs in background) accepting messages.
      - For each message it dispatches to the registered ``Handler``.
      - ``send(user_id, text)`` pushes a reply back to that user.
      - ``stop()`` cleans up.
    """

    name: str

    def __init__(self, handler: Handler):
        self.handler = handler

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def send(self, user_id: str, text: str) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...
