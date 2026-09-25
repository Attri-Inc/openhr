import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("OPENHR_DB", str(BASE_DIR / "data" / "openhr.db"))
MCP_PORT = int(os.getenv("MCP_PORT", "8792"))
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
