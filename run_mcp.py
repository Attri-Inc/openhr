#!/usr/bin/env python3
"""Entry point for OpenHR MCP server.

Defaults to stdio, which is what Claude Desktop and Claude Code spawn. Setting
MCP_TRANSPORT to `streamable-http` or `sse` is honoured here too, so the same
command serves a remote client (e.g. a Claude Cowork custom connector).
"""

import os
import sys

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MCP_TRANSPORT", "stdio")

from src.mcp_server import main  # noqa: E402  (import must follow the sys.path setup above)

main()
