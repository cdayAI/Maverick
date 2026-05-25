"""Channel base contract tests."""
from __future__ import annotations

from maverick_channels import Channel, Handler, IncomingMessage


def test_incoming_message_defaults():
    m = IncomingMessage(user_id="123", text="hello", channel="test")
    assert m.user_id == "123"
    assert m.text == "hello"
    assert m.channel == "test"
    assert m.attachments == []
    assert m.raw is None


def test_handler_type_exported():
    # Type alias; just confirm it's reachable.
    assert Handler is not None


def test_channel_is_abstract():
    # Channel is an ABC; subclasses must implement start/send/stop.
    import abc
    assert issubclass(Channel, abc.ABC) or hasattr(Channel, "__abstractmethods__")
