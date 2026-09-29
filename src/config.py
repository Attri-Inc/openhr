import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("OPENHR_DB", str(BASE_DIR / "data" / "openhr.db"))
MCP_PORT = int(os.getenv("MCP_PORT", "8792"))
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")


def _csv(name: str) -> list[str]:
    """Read a comma-separated env var into a list, dropping blanks."""
    return [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]


# Host/Origin allowlists for the HTTP transports.
#
# MCP's DNS-rebinding protection validates the Host header, and the SDK turns it
# on automatically when the server binds to loopback. Behind a tunnel or reverse
# proxy the Host header carries the *public* name, not 127.0.0.1, so a remote
# client is rejected with "Invalid Host header" (HTTP 421) until the operator
# declares that name here. Loopback is always allowed in addition to these.
#
#   MCP_ALLOWED_HOSTS=openhr.example.com,openhr.example.com:443
#
# Leaving it empty keeps the SDK's default, which is the safe, local-only one.
MCP_ALLOWED_HOSTS = _csv("MCP_ALLOWED_HOSTS")
MCP_ALLOWED_ORIGINS = _csv("MCP_ALLOWED_ORIGINS")
