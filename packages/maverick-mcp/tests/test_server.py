"""MCP server smoke + protocol tests.

v0.1.6: handle_tools_call now RAISES `_ProtocolError` for unknown tool /
missing required args (per MCP spec -- protocol errors must come back as
JSON-RPC `-32602`, not `isError`). Tests assert the exception is raised
and carries the right code. The `isError` envelope is only for tool
*execution* failures (e.g., the tool raised mid-call).
"""
from __future__ import annotations

import pytest

from maverick_mcp.server import (
    PROTOCOL_VERSION,
    TOOLS,
    MCPServer,
    _ProtocolError,
)


class TestTools:
    def test_all_tools_have_required_fields(self):
        for t in TOOLS:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t
            assert t["inputSchema"].get("type") == "object"

    def test_known_tool_names(self):
        names = {t["name"] for t in TOOLS}
        for expected in (
            "maverick_start",
            "maverick_status",
            "maverick_skill_install",
            "maverick_fact_set",
        ):
            assert expected in names


class TestProtocol:
    def test_initialize_response_shape(self):
        s = MCPServer()
        out = s.handle_initialize({})
        assert out["protocolVersion"] == PROTOCOL_VERSION
        assert out["serverInfo"]["name"] == "maverick"
        assert "capabilities" in out

    def test_tools_list_returns_full_catalog(self):
        s = MCPServer()
        out = s.handle_tools_list({})
        assert len(out["tools"]) == len(TOOLS)

    def test_unknown_tool_raises_protocol_error(self):
        """Unknown tool -> JSON-RPC -32602, not isError envelope."""
        s = MCPServer()
        with pytest.raises(_ProtocolError) as excinfo:
            s.handle_tools_call({"name": "does_not_exist", "arguments": {}})
        assert excinfo.value.code == -32602
        assert "unknown tool" in excinfo.value.message

    def test_missing_required_arg_raises_protocol_error(self):
        """Missing required arg -> JSON-RPC -32602."""
        s = MCPServer()
        # maverick_answer requires question_id + answer
        with pytest.raises(_ProtocolError) as excinfo:
            s.handle_tools_call({"name": "maverick_answer", "arguments": {}})
        assert excinfo.value.code == -32602
        assert "question_id" in excinfo.value.message
        assert "answer" in excinfo.value.message

    def test_tool_execution_failure_returns_isError_envelope(self):
        """Tool that raises mid-execution -> isError (not protocol error).

        maverick_facts_get touches WorldModel and would normally succeed;
        we'd need to mock it to force a raise. Skip the full path test and
        just verify the contract via _dispatch_tool returning isError when
        dispatch raises.
        """
        s = MCPServer()
        # All registered names dispatch normally. Force an exception
        # by passing a name the dispatch can find but the tool raises on.
        # maverick_answer with bad question_id type -> int() raises.
        out = s.handle_tools_call({
            "name": "maverick_answer",
            "arguments": {"question_id": "not-a-number", "answer": "x"},
        })
        assert out["isError"] is True
        assert "text" in out["content"][0]
