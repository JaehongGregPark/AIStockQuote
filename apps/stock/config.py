"""AIStockQuote 설정 모듈 — 원본 app/config.py를 허브 프로젝트 구조에 맞게 이식.

LLM 키/모델은 여전히 .env 파일에 영속화합니다(운영 중 설정 화면에서 바꾼 값이
서버 재시작 후에도 유지되도록). .env 파일은 허브 프로젝트 루트(manage.py 옆)를
기준으로 찾습니다.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv, set_key

_found_env_path = find_dotenv(usecwd=True)
ENV_FILE_PATH = Path(_found_env_path) if _found_env_path else (
    Path(__file__).resolve().parent.parent.parent / ".env"
)

load_dotenv(_found_env_path or None)

ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")

AI_PROVIDER: str | None = (os.getenv("AI_PROVIDER") or "").strip().lower() or None

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-5"
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-1.5-flash"

# 2026-07-22: aura(AURA)의 API key 관리 화면과 항목을 통일하면서 추가 -- "사용"
# 토글(끄면 활성 provider로 선택/자동선택되지 않음)과 운영자 메모.
# 기본값은 True(하위호환): 기존에 설정된 provider는 이 필드가 없어도 계속 동작해야 한다.
ANTHROPIC_ENABLED = os.getenv("ANTHROPIC_ENABLED", "1") != "0"
OPENAI_ENABLED = os.getenv("OPENAI_ENABLED", "1") != "0"
GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "1") != "0"

ANTHROPIC_MEMO = os.getenv("ANTHROPIC_MEMO") or ""
OPENAI_MEMO = os.getenv("OPENAI_MEMO") or ""
GEMINI_MEMO = os.getenv("GEMINI_MEMO") or ""

AI_REQUEST_TIMEOUT_SECONDS = int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "10"))
MARKET_CACHE_TTL_SECONDS = int(os.getenv("MARKET_CACHE_TTL_SECONDS", "60"))
DETAIL_CACHE_TTL_SECONDS = int(os.getenv("DETAIL_CACHE_TTL_SECONDS", "30"))
FETCH_MAX_WORKERS = int(os.getenv("FETCH_MAX_WORKERS", "10"))


def persist_env_value(key: str, value: str) -> None:
    ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(ENV_FILE_PATH), key, value)
