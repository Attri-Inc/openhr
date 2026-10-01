"""Tests for the HTTP transports' Host/Origin allowlist."""

from src import mcp_server
from src.mcp_server import LOOPBACK_HOSTS, transport_security


def test_no_allowlist_keeps_the_sdk_default(monkeypatch):
    monkeypatch.setattr(mcp_server, "MCP_ALLOWED_HOSTS", [])
    monkeypatch.setattr(mcp_server, "MCP_ALLOWED_ORIGINS", [])
    assert transport_security() is None


def test_declared_hosts_are_allowed_alongside_loopback(monkeypatch):
    monkeypatch.setattr(mcp_server, "MCP_ALLOWED_HOSTS", ["openhr.example.com"])
    monkeypatch.setattr(mcp_server, "MCP_ALLOWED_ORIGINS", [])
    settings = transport_security()
    assert settings is not None
    assert settings.allowed_hosts == ["openhr.example.com", *LOOPBACK_HOSTS]
    assert settings.allowed_origins == ["https://openhr.example.com"]


def test_wildcard_port_hosts_do_not_become_origins(monkeypatch):
    monkeypatch.setattr(mcp_server, "MCP_ALLOWED_HOSTS", ["openhr.example.com", "proxy:*"])
    monkeypatch.setattr(mcp_server, "MCP_ALLOWED_ORIGINS", [])
    settings = transport_security()
    assert settings is not None
    assert settings.allowed_origins == ["https://openhr.example.com"]


def test_explicit_origins_override_the_derived_ones(monkeypatch):
    monkeypatch.setattr(mcp_server, "MCP_ALLOWED_HOSTS", ["openhr.example.com"])
    monkeypatch.setattr(mcp_server, "MCP_ALLOWED_ORIGINS", ["https://claude.ai"])
    settings = transport_security()
    assert settings is not None
    assert settings.allowed_origins == ["https://claude.ai"]
