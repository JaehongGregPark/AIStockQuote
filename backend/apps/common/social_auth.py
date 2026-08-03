"""공용 소셜 로그인(OAuth) 헬퍼 — 카카오/네이버/구글/애플.

aura_app/stock(Django ORM 회원 모델, 서버 리다이렉트 방식)과 aerogo(Flutter
앱이 네이티브 SDK로 이미 얻은 access_token/id_token을 검증만 하면 되는 방식)가
함께 사용한다.

설계 메모:
- 카카오/네이버/구글은 "인가 코드" 흐름(authorize_url -> exchange_code ->
  fetch_profile)을 쓴다. aerogo처럼 클라이언트가 이미 access_token(카카오/네이버)
  이나 id_token(구글)을 갖고 있는 경우엔 fetch_profile_with_access_token /
  fetch_profile_with_id_token으로 바로 검증한다.
- 애플은 client_secret(개인키로 서명한 JWT) 발급이 필요 없는 방식만 지원한다.
  response_type=`code id_token`으로 요청하면 콜백에 id_token이 바로 실려오고,
  이를 애플 공개키(JWKS)로 서명 검증하는 것만으로 로그인을 완성할 수 있다 —
  Client ID(Services ID)만 있으면 되고 개인키/Key ID/Team ID 없이도 동작한다
  (자격증명을 아직 발급받지 못한 상태에서도 나머지 3개 공급자와 동일하게
  "Client ID만 채우면 켜진다" 방식을 유지하기 위한 선택).
- OAuth state 파라미터는 세션에 의존하지 않고 SECRET_KEY로 서명한 토큰을 쓴다.
  애플 콜백은 response_mode=form_post라 크로스사이트 POST로 들어오는데, 브라우저
  마다 SameSite=Lax 세션 쿠키가 그 요청에 실리는지 여부가 갈려서(정책 변경 이력이
  있음) 세션 기반 state 검증은 불안정하다. 서명 토큰은 쿠키 없이도 위변조 여부와
  만료를 검증할 수 있어 4개 공급자에 동일하게 적용 가능하다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core import signing
from dotenv import find_dotenv, set_key

PROVIDERS = ("kakao", "naver", "google", "apple")

PROVIDER_LABELS = {
    "kakao": "카카오",
    "naver": "네이버",
    "google": "구글",
    "apple": "애플",
}

STATE_SALT = "apps.common.social_auth.state"
STATE_MAX_AGE_SECONDS = 600  # 10분 -- 로그인 화면을 오래 띄워두면 다시 시도해야 함
REQUEST_TIMEOUT_SECONDS = 10


class SocialAuthError(Exception):
    """설정 누락, 공급자 API 오류, 토큰/서명 검증 실패 등 모든 소셜 로그인 오류."""


@dataclass
class SocialProfile:
    provider: str
    uid: str
    email: str = ""
    name: str = ""


def _require_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise SocialAuthError(f"지원하지 않는 소셜 로그인 공급자입니다: {provider}")


# ---------------------------------------------------------------------------
# 관리자 화면에서 Client ID/Secret을 저장하는 기능(5개 서브앱 공용).
#
# 기존에는 SOCIAL_*_CLIENT_ID/SECRET을 config/settings.py가 프로세스 시작 시
# os.environ에서 한 번만 읽어 django.conf.settings에 고정해뒀다 — .env를 고쳐도
# 서버를 재시작해야 반영됐다(docs/소셜로그인_연동_가이드.md). apps/stock/config.py의
# AI 공급자 설정 패널(재시작 없이 즉시 반영)과 동일한 UX를 주기 위해, 이 모듈에
# "런타임 오버라이드" 저장소를 두고 client_id()/client_secret()이 여길 먼저
# 확인하게 한다. 저장 시 .env에도 python-dotenv로 같이 써서(persist_credential)
# 다음 재시작 후에도 유지되게 한다.
#
# social_auth.py는 5개 앱이 전부 공유하는 단일 모듈이므로, 여기 오버라이드는
# 프로세스 전체(=5개 앱 전부)에 즉시 반영된다 — 카카오/네이버/구글/애플 앱은
# 원래 허브 전체에서 자격증명 하나씩만 쓰는 구조라(docs 참고, 콜백 URI를
# 앱마다 20개 등록) 이건 버그가 아니라 의도된 동작이다. 앱마다 다른 관리자
# 각 서비스 화면에서 저장해도 결과는 같은 자격증명이다.
# ---------------------------------------------------------------------------

_RUNTIME_OVERRIDES: dict = {}

_found_env_path = find_dotenv(usecwd=True)
_ENV_FILE_PATH = Path(_found_env_path) if _found_env_path else (
    Path(__file__).resolve().parent.parent.parent / ".env"
)


# 2026-07-22: 관리자 화면을 LinguaUp(language.it.kr) 백오피스 형태로 통일하면서
# client_id/client_secret 2개뿐이던 필드를 실제로 동작하는 기능으로 확장했다 --
# 제공사별 사용/미사용 토글, Redirect URI/Scope 오버라이드, 애플 전용
# Team ID/Key ID/Private Key. 새 필드는 전부 "비어있으면 기존 동작 그대로"가
# 기본값이라(토글은 예외 -- 아래 is_enabled() 설명 참고) 기존에 이미 동작하던
# 설정을 건드리지 않는다.
_GENERIC_FIELDS = {
    "client_id": "CLIENT_ID",
    "client_secret": "CLIENT_SECRET",
    "is_enabled": "ENABLED",
    "redirect_uri": "REDIRECT_URI",
    "scope": "SCOPE",
}
# 애플만 추가로 갖는 필드(다른 3개 공급사는 해당 없음 -- client_secret용
# JWT를 개인키로 서명해야 하는 애플만의 요구사항).
_APPLE_ONLY_FIELDS = {
    "apple_team_id": "SOCIAL_APPLE_TEAM_ID",
    "apple_key_id": "SOCIAL_APPLE_KEY_ID",
    "apple_private_key": "SOCIAL_APPLE_PRIVATE_KEY",
}


def _env_var_name(provider: str, field: str) -> str:
    _require_provider(provider)
    if field in _APPLE_ONLY_FIELDS:
        if provider != "apple":
            raise SocialAuthError(f"{field}는 애플 전용 필드입니다.")
        return _APPLE_ONLY_FIELDS[field]
    if field not in _GENERIC_FIELDS:
        raise SocialAuthError(f"알 수 없는 필드입니다: {field}")
    return f"SOCIAL_{provider.upper()}_{_GENERIC_FIELDS[field]}"


def _read_raw(key: str) -> str:
    if key in _RUNTIME_OVERRIDES:
        return _RUNTIME_OVERRIDES[key]
    return (getattr(settings, key, "") or "").strip()


def client_id(provider: str) -> str:
    return _read_raw(_env_var_name(provider, "client_id"))


def client_secret(provider: str) -> str:
    return _read_raw(_env_var_name(provider, "client_secret"))


def is_enabled(provider: str) -> bool:
    """이 제공사로 로그인을 사용할지 여부 (관리자 화면의 "사용/미사용" 토글).

    비어있으면(=한 번도 명시적으로 끈 적 없으면) True로 취급한다 -- 이 토글이
    생기기 전부터 이미 Client ID만으로 동작하던 기존 설정이 이 필드 추가만으로
    갑자기 로그인이 막히는 회귀를 막기 위함이다. "0"으로 저장된 경우에만 꺼진다.
    """
    raw = _read_raw(_env_var_name(provider, "is_enabled"))
    return raw != "0"


def redirect_uri_override(provider: str) -> str:
    return _read_raw(_env_var_name(provider, "redirect_uri"))


def scope_override(provider: str) -> str:
    return _read_raw(_env_var_name(provider, "scope"))


def effective_redirect_uri(provider: str, default_redirect_uri: str) -> str:
    """관리자가 Redirect URI를 직접 입력했으면 그 값을, 비어있으면 각 앱이
    계산한 기본 콜백 URL(default_redirect_uri)을 그대로 쓴다."""
    return redirect_uri_override(provider) or default_redirect_uri


def apple_team_id() -> str:
    return _read_raw(_env_var_name("apple", "apple_team_id"))


def apple_key_id() -> str:
    return _read_raw(_env_var_name("apple", "apple_key_id"))


def apple_private_key() -> str:
    return _read_raw(_env_var_name("apple", "apple_private_key"))


def mask_secret(value: str) -> str:
    """앞 4글자만 보여주고 나머지는 가린다 (예: 관리자 화면에 표시용)."""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return value[:4] + "*" * min(len(value) - 4, 20)


_SECRET_FIELDS = {"client_secret", "apple_private_key"}
_BOOL_FIELDS = {"is_enabled"}


def persist_credential(provider: str, field: str, value) -> None:
    """설정 필드 하나를 즉시(재시작 없이) 반영하고 .env에도 저장한다.

    apps/stock/config.py의 persist_env_value와 동일한 방식(python-dotenv
    set_key)을 쓰되, 5개 앱이 공유하는 이 모듈 하나에서 관리한다. is_enabled는
    bool을 "1"/"0" 문자열로 저장한다(.env는 문자열만 담을 수 있으므로).
    """
    key = _env_var_name(provider, field)
    if field in _BOOL_FIELDS:
        value = "1" if value else "0"
    else:
        value = (value or "").strip()
    _RUNTIME_OVERRIDES[key] = value
    _ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    set_key(str(_ENV_FILE_PATH), key, value)


def save_credential_from_form(provider: str, post_data) -> None:
    """일반 HTML <form method="post"> 제출(aura_app/origin/aerogo의 소셜로그인
    탭이 쓰는 방식 -- stock만 JSON API를 따로 씀)을 그대로 받아 저장한다.

    체크박스(is_enabled)는 켜져 있을 때만 POST 바디에 필드 자체가 실리는 HTML
    표준 동작을 그대로 따른다 -- "is_enabled" in post_data로 판정한다.
    """
    _require_provider(provider)
    persist_credential(provider, "client_id", post_data.get("client_id", ""))
    persist_credential(provider, "client_secret", post_data.get("client_secret", ""))
    persist_credential(provider, "redirect_uri", post_data.get("redirect_uri", ""))
    persist_credential(provider, "scope", post_data.get("scope", ""))
    persist_credential(provider, "is_enabled", "is_enabled" in post_data)
    if provider == "apple":
        persist_credential(provider, "apple_team_id", post_data.get("apple_team_id", ""))
        persist_credential(provider, "apple_key_id", post_data.get("apple_key_id", ""))
        persist_credential(provider, "apple_private_key", post_data.get("apple_private_key", ""))


def credential_status() -> list:
    """관리자 화면에 뿌릴 공급자별 설정 상태 목록."""
    rows = []
    for provider in PROVIDERS:
        cid = client_id(provider)
        secret = client_secret(provider)
        row = {
            "provider": provider,
            "label": PROVIDER_LABELS[provider],
            "client_id": cid,
            "client_id_masked": mask_secret(cid),
            "has_client_id": bool(cid),
            "has_client_secret": bool(secret),
            "client_secret_masked": mask_secret(secret),
            "configured": is_configured(provider),
            "requires_secret": provider in ("naver", "google"),
            "is_enabled": is_enabled(provider),
            "redirect_uri": redirect_uri_override(provider),
            "scope": scope_override(provider),
        }
        if provider == "apple":
            row["apple_team_id"] = apple_team_id()
            row["apple_key_id"] = apple_key_id()
            row["has_apple_private_key"] = bool(apple_private_key())
        rows.append(row)
    return rows


def is_configured(provider: str) -> bool:
    """Client ID가 있고, 관리자가 "사용" 토글을 끄지 않았으면 "설정됨"으로 본다.

    카카오는 Client Secret이 콘솔에서 켠 앱만 필요하고, 애플은 위 모듈 설명대로
    Client ID(Services ID)만으로 id_token 검증이 가능해서, 4개 공급자 모두 이
    한 가지 기준(+토글)으로 로그인 버튼 노출 여부를 결정할 수 있다.
    """
    return bool(client_id(provider)) and is_enabled(provider)


def configured_providers() -> list:
    return [provider for provider in PROVIDERS if is_configured(provider)]


def sign_state(payload: dict) -> str:
    return signing.dumps(payload, salt=STATE_SALT)


def unsign_state(state: str) -> dict:
    try:
        return signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE_SECONDS)
    except signing.BadSignature as exc:
        raise SocialAuthError("로그인 요청이 올바르지 않거나 만료되었습니다. 다시 시도해 주세요.") from exc


def authorize_url(provider: str, redirect_uri: str, state: str, *, scope: str | None = None) -> str:
    """`scope`를 넘기지 않거나 빈 문자열이면 공급자별 기존 기본값을 그대로
    쓴다(관리자 화면에서 Scope를 비워두면 기존 동작과 동일하다는 뜻) --
    social_auth.scope_override(provider)의 값을 호출부에서 넘겨주면 된다."""
    _require_provider(provider)
    if not is_configured(provider):
        raise SocialAuthError(
            f"{PROVIDER_LABELS[provider]} 로그인이 아직 설정되지 않았거나 비활성화되어 있습니다. "
            f"관리자 화면의 소셜로그인 탭에서 Client ID와 '사용' 토글을 확인하세요."
        )
    cid = client_id(provider)

    if provider == "kakao":
        params = {
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        if scope:
            params["scope"] = scope
        return f"https://kauth.kakao.com/oauth/authorize?{urlencode(params)}"

    if provider == "naver":
        params = {
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if scope:
            params["scope"] = scope
        return f"https://nid.naver.com/oauth2.0/authorize?{urlencode(params)}"

    if provider == "google":
        params = {
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope or "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    # apple
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code id_token",
        "response_mode": "form_post",
        "scope": scope or "name email",
        "state": state,
    }
    return f"https://appleid.apple.com/auth/authorize?{urlencode(params)}"


# ---------------------------------------------------------------------------
# 애플 client_secret(JWT) 생성 -- ES256으로 서명한다.
#
# 현재 로그인 흐름(verify_apple_id_token) 자체는 client_secret이 필요 없다
# (모듈 상단 설명 참고: response_type=`code id_token`으로 콜백에 id_token이
# 바로 실려오므로). 하지만 애플 토큰/리프레시/해지(revoke) API는 전부
# client_secret(JWT)을 요구하므로, Team ID/Key ID/Private Key를 실제로
# 쓸모 있게 하려면 이 함수가 필요하다 -- 관리자 화면에 그 3개 필드를 두는
# 이상 장식이 아니라 실제로 유효한 JWT를 만들어내야 한다.
# ---------------------------------------------------------------------------

def generate_apple_client_secret(*, expires_in_seconds: int = 15777000) -> str:
    """애플 Team ID/Key ID/Private Key로 client_secret(JWT)을 서명해 반환한다.

    expires_in_seconds 기본값(약 6개월)은 애플이 허용하는 최대값이다. 세
    필드 중 하나라도 비어있으면 SocialAuthError를 던진다.
    """
    import time

    import jwt

    team_id = apple_team_id()
    key_id = apple_key_id()
    private_key = apple_private_key()
    cid = client_id("apple")

    if not (team_id and key_id and private_key and cid):
        raise SocialAuthError(
            "애플 Team ID/Key ID/Private Key/Client ID가 모두 있어야 client_secret을 생성할 수 있습니다."
        )

    now = int(time.time())
    payload = {
        "iss": team_id,
        "iat": now,
        "exp": now + expires_in_seconds,
        "aud": "https://appleid.apple.com",
        "sub": cid,
    }
    try:
        return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": key_id})
    except Exception as exc:  # noqa: BLE001 - private key 형식 오류 등을 그대로 노출
        raise SocialAuthError(f"애플 client_secret 생성에 실패했습니다: {exc}") from exc


def exchange_code(provider: str, code: str, redirect_uri: str) -> dict:
    """인가 코드를 토큰으로 교환한다. 애플은 이 함수를 쓰지 않는다(모듈 설명 참고)."""
    _require_provider(provider)
    cid = client_id(provider)
    secret = client_secret(provider)

    if provider == "kakao":
        data = {
            "grant_type": "authorization_code",
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        if secret:
            data["client_secret"] = secret
        response = requests.post(
            "https://kauth.kakao.com/oauth/token", data=data, timeout=REQUEST_TIMEOUT_SECONDS
        )
    elif provider == "naver":
        data = {
            "grant_type": "authorization_code",
            "client_id": cid,
            "client_secret": secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        response = requests.post(
            "https://nid.naver.com/oauth2.0/token", data=data, timeout=REQUEST_TIMEOUT_SECONDS
        )
    elif provider == "google":
        data = {
            "grant_type": "authorization_code",
            "client_id": cid,
            "client_secret": secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        response = requests.post(
            "https://oauth2.googleapis.com/token", data=data, timeout=REQUEST_TIMEOUT_SECONDS
        )
    else:
        raise SocialAuthError("애플은 인가 코드 교환 방식을 쓰지 않습니다.")

    if response.status_code != 200:
        raise SocialAuthError(
            f"{PROVIDER_LABELS[provider]} 토큰 발급에 실패했습니다 (HTTP {response.status_code})."
        )
    return response.json()


def _fetch_kakao_profile(access_token: str) -> SocialProfile:
    if not access_token:
        raise SocialAuthError("카카오 access_token이 없습니다.")
    response = requests.get(
        "https://kapi.kakao.com/v2/user/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise SocialAuthError(f"카카오 프로필 조회에 실패했습니다 (HTTP {response.status_code}).")
    payload = response.json()
    account = payload.get("kakao_account") or {}
    profile = account.get("profile") or {}
    return SocialProfile(
        provider="kakao",
        uid=str(payload.get("id") or ""),
        email=(account.get("email") or "").strip(),
        name=(profile.get("nickname") or "").strip(),
    )


def _fetch_naver_profile(access_token: str) -> SocialProfile:
    if not access_token:
        raise SocialAuthError("네이버 access_token이 없습니다.")
    response = requests.get(
        "https://openapi.naver.com/v1/nid/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise SocialAuthError(f"네이버 프로필 조회에 실패했습니다 (HTTP {response.status_code}).")
    payload = response.json()
    if payload.get("resultcode") != "00":
        raise SocialAuthError(payload.get("message") or "네이버 프로필 조회에 실패했습니다.")
    account = payload.get("response") or {}
    return SocialProfile(
        provider="naver",
        uid=str(account.get("id") or ""),
        email=(account.get("email") or "").strip(),
        name=(account.get("name") or account.get("nickname") or "").strip(),
    )


def _fetch_google_profile(access_token: str) -> SocialProfile:
    if not access_token:
        raise SocialAuthError("구글 access_token이 없습니다.")
    response = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise SocialAuthError(f"구글 프로필 조회에 실패했습니다 (HTTP {response.status_code}).")
    payload = response.json()
    return SocialProfile(
        provider="google",
        uid=str(payload.get("sub") or ""),
        email=(payload.get("email") or "").strip(),
        name=(payload.get("name") or "").strip(),
    )


def fetch_profile(provider: str, token_response: dict) -> SocialProfile:
    """exchange_code()가 반환한 토큰 응답으로 프로필을 조회한다(애플 제외)."""
    _require_provider(provider)
    access_token = token_response.get("access_token", "")
    if provider == "kakao":
        return _fetch_kakao_profile(access_token)
    if provider == "naver":
        return _fetch_naver_profile(access_token)
    if provider == "google":
        id_token = token_response.get("id_token", "")
        if id_token:
            return verify_google_id_token(id_token)
        return _fetch_google_profile(access_token)
    raise SocialAuthError("애플은 이 함수를 쓰지 않습니다 — verify_apple_id_token을 사용하세요.")


def fetch_profile_with_access_token(provider: str, access_token: str) -> SocialProfile:
    """aerogo(Flutter)처럼 클라이언트가 이미 얻은 access_token만 검증하는 경로."""
    _require_provider(provider)
    if provider == "kakao":
        return _fetch_kakao_profile(access_token)
    if provider == "naver":
        return _fetch_naver_profile(access_token)
    if provider == "google":
        return _fetch_google_profile(access_token)
    raise SocialAuthError("애플은 access_token이 아닌 id_token 방식입니다.")


def fetch_profile_with_id_token(provider: str, id_token: str) -> SocialProfile:
    _require_provider(provider)
    if provider == "google":
        return verify_google_id_token(id_token)
    if provider == "apple":
        return verify_apple_id_token(id_token)
    raise SocialAuthError(f"{PROVIDER_LABELS[provider]}는 id_token 방식이 아닌 access_token 방식입니다.")


_JWKS_CLIENTS = {}


def _jwks_client(jwks_url: str):
    # PyJWT는 지연 임포트한다 — 이 모듈 자체는 requirements에 PyJWT를 추가하기 전에도
    # (카카오/네이버 access_token 경로만 쓰는 한) import에 실패하지 않아야 하기 때문.
    import jwt

    client = _JWKS_CLIENTS.get(jwks_url)
    if client is None:
        client = jwt.PyJWKClient(jwks_url, cache_keys=True)
        _JWKS_CLIENTS[jwks_url] = client
    return client


def _verify_id_token(*, id_token: str, jwks_url: str, issuers: Iterable, audience: str, provider_label: str) -> dict:
    import jwt

    if not id_token:
        raise SocialAuthError(f"{provider_label} id_token이 없습니다.")
    if not audience:
        raise SocialAuthError(f"{provider_label} Client ID가 설정되지 않았습니다.")
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise SocialAuthError(f"{provider_label} id_token 검증에 실패했습니다: {exc}") from exc

    if claims.get("iss") not in issuers:
        raise SocialAuthError(f"{provider_label} id_token의 발급자(iss)가 올바르지 않습니다.")
    return claims


def verify_google_id_token(id_token: str) -> SocialProfile:
    claims = _verify_id_token(
        id_token=id_token,
        jwks_url="https://www.googleapis.com/oauth2/v3/certs",
        issuers=("https://accounts.google.com", "accounts.google.com"),
        audience=client_id("google"),
        provider_label="구글",
    )
    return SocialProfile(
        provider="google",
        uid=str(claims.get("sub") or ""),
        email=(claims.get("email") or "").strip(),
        name=(claims.get("name") or "").strip(),
    )


def verify_apple_id_token(id_token: str) -> SocialProfile:
    """애플 id_token을 검증한다.

    이름은 id_token에 담기지 않는다 — 최초 로그인 1회에 한해 콜백 form_post의
    `user` 파라미터(JSON 문자열)로만 내려온다. 필요하면 호출부(콜백 뷰)에서
    request.POST.get("user")를 별도로 파싱해 SocialProfile.name을 채워 넣는다.
    """
    claims = _verify_id_token(
        id_token=id_token,
        jwks_url="https://appleid.apple.com/auth/keys",
        issuers=("https://appleid.apple.com",),
        audience=client_id("apple"),
        provider_label="애플",
    )
    return SocialProfile(
        provider="apple",
        uid=str(claims.get("sub") or ""),
        email=(claims.get("email") or "").strip(),
        name="",
    )
