"""공용 뉴스 조회 헬퍼 -- AeroGo(바둑뉴스)/Stock(주식뉴스)가 함께 쓴다.

GNews API(https://gnews.io, /api/v4/search)를 기본 provider로 사용한다. 무료
요금제는 하루 호출 횟수가 적어서 짧은 TTL 메모리 캐시를 둔다. GNews가 특정
키워드/지역에서 컨텐츠 제약(라이선스 미보유 등)으로 결과를 주지 못하거나 계정
자체에 문제가 생기는 경우를 대비해, fetch 진입점을 이 모듈 하나로 좁혀뒀다 --
다른 뉴스 서비스로 바꿀 때는 `_fetch_from_gnews()`만 교체하면 호출부(각 앱의
view)는 그대로 둘 수 있다.

API key 저장 방식은 apps/common/social_auth.py의 소셜로그인 자격증명과 동일하다:
런타임 오버라이드 변수 + .env 파일(python-dotenv)에 즉시 반영해서 프로세스
재시작 없이 바로 사용 가능하다. 허브 전체가 GNews 계정 하나를 공유한다(소셜로그인
자격증명과 같은 설계 -- AeroGo/Stock 관리자 화면 중 어디서 저장해도 같은 값을 본다).
"""
from __future__ import annotations

import html
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings
from dotenv import find_dotenv, set_key

from apps.common.social_auth import mask_secret

ENV_KEY_NAME = "NEWS_GNEWS_API_KEY"
REQUEST_TIMEOUT_SECONDS = 10
CACHE_TTL_SECONDS = 600  # 10분 -- 무료 요금제 호출 횟수를 아끼기 위한 최소한의 캐시
GNEWS_SEARCH_URL = "https://gnews.io/api/v4/search"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
GOOGLE_NEWS_SEARCH_URL = "https://news.google.com/search"

# GNews /search가 실제로 필터링 가능한 lang 값 목록(2026-07-25, docs.gnews.io/
# endpoints/search-endpoint 확인). **한국어(ko)는 이 목록에 없다** -- 지원하지
# 않는 코드를 lang에 넣어도 API가 에러를 내지 않고 그냥 0건을 돌려주기 때문에,
# 바둑뉴스/주식뉴스 둘 다 검증(키 자체)은 성공하는데 실제 조회는 항상 빈 배열만
# 나오는 원인이었다 -- q에 이미 한글 키워드가 들어있으니 lang 필터 없이도(Any)
# 한국어 기사는 키워드 매칭으로 충분히 잡힌다.
GNEWS_SUPPORTED_LANGS = {
    "ar", "bn", "zh", "nl", "en", "fr", "de", "el", "he", "hi", "id", "it",
    "ja", "ml", "mr", "no", "pt", "pa", "ro", "ru", "es", "sv", "ta", "te",
    "tr", "uk",
}

_RUNTIME_OVERRIDE: Optional[str] = None

_found_env_path = find_dotenv(usecwd=True)
_ENV_FILE_PATH = Path(_found_env_path) if _found_env_path else (
    Path(__file__).resolve().parent.parent.parent / ".env"
)

# cache_key -> (모노토닉 timestamp, articles)
_cache: dict = {}


class NewsServiceError(Exception):
    """뉴스 조회에 실패했지만 호출부가 사용자에게 그대로 보여줄 수 있는 오류 메시지."""


def get_api_key() -> str:
    if _RUNTIME_OVERRIDE is not None:
        return _RUNTIME_OVERRIDE
    return (getattr(settings, ENV_KEY_NAME, "") or "").strip()


def is_configured() -> bool:
    return bool(get_api_key())


def save_api_key(value: str) -> None:
    """key를 즉시(재시작 없이) 반영하고 .env에도 저장한다 -- social_auth.persist_credential과 동일한 패턴."""
    global _RUNTIME_OVERRIDE
    value = (value or "").strip()
    _RUNTIME_OVERRIDE = value
    _ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(_ENV_FILE_PATH), ENV_KEY_NAME, value)


def masked_api_key() -> str:
    return mask_secret(get_api_key())


def status_payload() -> dict:
    return {
        "provider": "gnews",
        "label": "GNews",
        "hasKey": is_configured(),
        "maskedKey": masked_api_key(),
    }


def _normalize_article(item: dict) -> dict:
    source = item.get("source") or {}
    return {
        "title": item.get("title") or "",
        "description": item.get("description") or "",
        "content": item.get("content") or "",
        "url": item.get("url") or "",
        "image": item.get("image") or "",
        "publishedAt": item.get("publishedAt") or "",
        "sourceName": source.get("name") or "",
    }


def _fetch_from_gnews(query: str, *, lang: Optional[str], max_results: int) -> list:
    api_key = get_api_key()
    if not api_key:
        raise NewsServiceError("GNews API key가 설정되어 있지 않습니다.")

    params = {
        "q": query,
        "max": max(1, min(max_results, 25)),
        "sortby": "publishedAt",
        "apikey": api_key,
    }
    # 미지원 lang 코드(예: ko)를 그대로 보내면 GNews가 에러 없이 0건을 반환한다 --
    # 지원 목록에 있을 때만 필터를 건다(GNEWS_SUPPORTED_LANGS 주석 참고).
    if lang and lang in GNEWS_SUPPORTED_LANGS:
        params["lang"] = lang
    try:
        response = requests.get(GNEWS_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout as error:
        raise NewsServiceError("뉴스 조회 요청 시간이 초과되었습니다.") from error
    except requests.exceptions.RequestException as error:
        raise NewsServiceError(f"뉴스 조회 네트워크 오류: {error}") from error

    if response.status_code in (401, 403):
        raise NewsServiceError("GNews API key 인증에 실패했습니다. key를 다시 확인해 주세요.")
    if response.status_code == 429:
        raise NewsServiceError("GNews 요청 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.")
    if not response.ok:
        raise NewsServiceError(f"GNews 응답 오류(status={response.status_code}).")

    try:
        payload = response.json()
    except ValueError as error:
        raise NewsServiceError("GNews 응답을 해석하지 못했습니다.") from error

    return [_normalize_article(item) for item in payload.get("articles", [])]


def _plain_text_from_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _add_google_news_images(query: str, articles: list) -> None:
    """검색 페이지의 기사 ID와 썸네일을 대응시켜 RSS 기사에 이미지를 보충한다.

    Google RSS 자체에는 이미지 필드가 없지만 같은 검색의 웹 결과에는 썸네일이 있다.
    웹 마크업이 바뀌거나 요청이 실패해도 뉴스 목록 자체는 그대로 사용할 수 있도록
    이 보강 단계의 실패는 조용히 무시한다.
    """
    try:
        response = requests.get(
            GOOGLE_NEWS_SEARCH_URL,
            params={"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException:
        return
    if not response.ok:
        return

    page = response.text
    for article in articles:
        article_id = urlparse(article["url"]).path.rstrip("/").rsplit("/", 1)[-1]
        if not article_id:
            continue
        article_position = page.find(article_id)
        if article_position < 0:
            continue
        image_start = page.rfind(
            '<img class="Quavad',
            max(0, article_position - 15_000),
            article_position,
        )
        if image_start < 0:
            image_start = page.find(
                '<img class="Quavad',
                article_position,
                min(len(page), article_position + 15_000),
            )
        if image_start < 0:
            continue
        image_end = page.find(">", image_start, image_start + 2_000)
        if image_end < 0:
            continue
        image_tag = page[image_start:image_end + 1]
        source_match = re.search(r'\bsrc="([^"]+)"', image_tag)
        if source_match:
            article["image"] = urljoin(
                "https://news.google.com/",
                html.unescape(source_match.group(1)),
            )


def _fetch_from_google_news_rss(query: str, *, max_results: int) -> list:
    """Google News 한국어 RSS를 공통 뉴스 형식으로 변환한다.

    RSS에는 대표 이미지가 없으므로 image/content는 빈 문자열로 둔다. description은
    Google이 제공하는 HTML 목록을 제거한 텍스트 요약으로 사용한다.
    """
    try:
        response = requests.get(
            GOOGLE_NEWS_RSS_URL,
            params={"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout as error:
        raise NewsServiceError("Google News RSS 조회 요청 시간이 초과되었습니다.") from error
    except requests.exceptions.RequestException as error:
        raise NewsServiceError(f"Google News RSS 네트워크 오류: {error}") from error

    if not response.ok:
        raise NewsServiceError(f"Google News RSS 응답 오류(status={response.status_code}).")

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as error:
        raise NewsServiceError("Google News RSS 응답을 해석하지 못했습니다.") from error

    articles = []
    limit = max(1, min(max_results, 25))
    for item in root.findall("./channel/item")[:limit]:
        published_at = item.findtext("pubDate") or ""
        if published_at:
            try:
                published_at = parsedate_to_datetime(published_at).isoformat()
            except (TypeError, ValueError):
                pass
        articles.append(
            {
                "title": item.findtext("title") or "",
                "description": _plain_text_from_html(item.findtext("description") or ""),
                "content": "",
                "url": item.findtext("link") or "",
                "image": "",
                "publishedAt": published_at,
                "sourceName": item.findtext("source") or "Google News",
            }
        )
    _add_google_news_images(query, articles)
    return articles


def fetch_news(
    query: str,
    *,
    lang: Optional[str] = "ko",
    max_results: int = 12,
    cache_key: Optional[str] = None,
    google_rss_fallback: bool = False,
) -> dict:
    """뉴스 목록을 가져온다. 실패해도 예외를 던지지 않고 available=False로 응답한다
    (호출부가 그대로 500 없이 JSON/템플릿을 렌더링할 수 있게 하기 위함 -- aura의
    vision_analysis 실패 폴백과 같은 설계 원칙).
    """

    if not is_configured() and not google_rss_fallback:
        return {"available": False, "reason": "no_key", "articles": [], "cached": False}

    key = cache_key or f"{query}|{lang}|{max_results}|rss={google_rss_fallback}"
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
        return {"available": True, "articles": cached[1], "cached": True, "provider": cached[2]}

    gnews_error = None
    try:
        articles = _fetch_from_gnews(query, lang=lang, max_results=max_results) if is_configured() else []
    except NewsServiceError as error:
        gnews_error = error
        articles = []

    provider = "gnews"
    if google_rss_fallback and not articles:
        try:
            articles = _fetch_from_google_news_rss(query, max_results=max_results)
            provider = "google_news_rss"
        except NewsServiceError as rss_error:
            if cached:
                warning = str(rss_error)
                if gnews_error:
                    warning = f"{gnews_error} / {warning}"
                return {
                    "available": True,
                    "articles": cached[1],
                    "cached": True,
                    "stale": True,
                    "warning": warning,
                    "provider": cached[2],
                }
            error = rss_error if not gnews_error else NewsServiceError(f"{gnews_error} / {rss_error}")
            return {
                "available": False,
                "reason": "provider_error",
                "error": str(error),
                "articles": [],
                "cached": False,
            }

    if gnews_error and not google_rss_fallback:
        if cached:
            return {
                "available": True,
                "articles": cached[1],
                "cached": True,
                "stale": True,
                "warning": str(gnews_error),
                "provider": cached[2],
            }
        return {
            "available": False,
            "reason": "provider_error",
            "error": str(gnews_error),
            "articles": [],
            "cached": False,
        }

    _cache[key] = (now, articles, provider)
    return {"available": True, "articles": articles, "cached": False, "provider": provider}


def validate_api_key() -> tuple:
    """저장된 key가 실제로 동작하는지 최소 호출(max=1)로 확인한다. 반환: (is_valid, message)."""
    api_key = get_api_key()
    if not api_key:
        return False, "저장된 API key가 없습니다."

    try:
        response = requests.get(
            GNEWS_SEARCH_URL,
            params={"q": "news", "max": 1, "apikey": api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        return False, "검증 요청 시간이 초과되었습니다."
    except requests.exceptions.RequestException as error:
        return False, f"네트워크 오류: {error}"

    if response.status_code in (401, 403):
        return False, f"인증 실패({response.status_code}): key 값을 다시 확인해 주세요."
    if response.status_code == 429:
        return False, "요청 한도를 초과했습니다(key 자체는 형식상 유효할 수 있습니다)."
    if 200 <= response.status_code < 300:
        return True, "API key가 유효합니다."
    return False, f"예상하지 못한 응답 상태: {response.status_code}"


def clear_cache() -> None:
    _cache.clear()
