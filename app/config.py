"""Centralized application configuration.

Loads environment variables from a local .env file (if present) so that
other modules can simply read from os.environ / os.getenv.
"""
import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")

# Cache TTLs (seconds)
MARKET_CACHE_TTL_SECONDS = int(os.getenv("MARKET_CACHE_TTL_SECONDS", "60"))
DETAIL_CACHE_TTL_SECONDS = int(os.getenv("DETAIL_CACHE_TTL_SECONDS", "30"))

# Thread pool size used for parallel yfinance calls
FETCH_MAX_WORKERS = int(os.getenv("FETCH_MAX_WORKERS", "10"))
