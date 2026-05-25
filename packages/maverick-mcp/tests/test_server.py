"""MCP server smoke tests."""
from __future__ import annotations

from maverick_mcp.server import PROTOCOL_VERSION, TOOLS, MCPServer


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

    def test_unknown_tool_returns_error_payload(self):
        s = MCPServer()
        out = s.handle_tools_call({"name": "does_not_exist", "arguments": {}})
        assert out["isError"] is True
        assert "unknown tool" in out["content"][0]["text"]

    def test_missing_required_arg_returns_error(self):
        s = MCPServer()
        out = s.handle_tools_call({"name": "maverick_answer", "arguments": {}})
        assert out["isError"] is True
