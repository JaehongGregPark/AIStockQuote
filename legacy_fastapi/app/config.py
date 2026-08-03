"""Centralized application configuration.

Loads environment variables from a local .env file (if present) so that
other modules can simply read from os.environ / os.getenv.
"""
import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv, set_key

# Resolve the actual .env file being used (if any) so runtime changes can be
# written back to the SAME file. If no .env exists yet, default to one next
# to the project root — it will be created on first write.
_found_env_path = find_dotenv(usecwd=True)
ENV_FILE_PATH = Path(_found_env_path) if _found_env_path else (
    Path(__file__).resolve().parent.parent / ".env"
)

load_dotenv(_found_env_path or None)

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")

# Explicit provider override ("anthropic" | "openai" | "gemini"). If unset,
# the first provider with a configured API key is used, in that order.
AI_PROVIDER: str | None = (os.getenv("AI_PROVIDER") or "").strip().lower() or None

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-1.5-flash"

# How long to wait on a single AI provider API call before giving up.
# Keeps a misconfigured/unreachable provider from hanging the whole request
# (e.g. the API-key check panel) indefinitely.
AI_REQUEST_TIMEOUT_SECONDS = int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "10"))

# Cache TTLs (seconds)
MARKET_CACHE_TTL_SECONDS = int(os.getenv("MARKET_CACHE_TTL_SECONDS", "60"))
DETAIL_CACHE_TTL_SECONDS = int(os.getenv("DETAIL_CACHE_TTL_SECONDS", "30"))

# Thread pool size used for parallel yfinance calls
FETCH_MAX_WORKERS = int(os.getenv("FETCH_MAX_WORKERS", "10"))


def persist_env_value(key: str, value: str) -> None:
    """Write `key=value` into the .env file (creating it if it doesn't
    exist yet), so the value survives a server restart. This does not by
    itself update the in-process value — callers should also
    `setattr(config, ...)` (or equivalent) alongside this call.
    """
    ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(ENV_FILE_PATH), key, value)
