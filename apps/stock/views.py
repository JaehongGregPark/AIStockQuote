"""AIStockQuote를 FastAPI에서 Django(async view)로 이식한 뷰.

라우팅/직렬화 레이어만 Django에 맞게 새로 작성했고, 실제 비즈니스 로직
(시세 조회, AI 분석, 캐싱)은 apps/stock/domain/ 아래 원본 서비스 모듈을
그대로 재사용합니다.

2026-07: 회원가입/로그인/비밀번호 찾기·변경 기능을 AURA(apps/aura_app/views.py)와
동일한 패턴으로 추가했습니다 (이메일=아이디, DB에 저장된 1회용 토큰으로 이메일
인증/비밀번호 재설정 처리). 주소는 국내 회원 위주라 다음 우편번호 팝업 결과에
맞춘 구조화된 필드(postal_code/road_address/address_detail)로 받습니다.
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import smtplib
from datetime import timedelta, timezone as dt_timezone
from functools import partial, wraps
from json import JSONDecodeError
from urllib.parse import quote as urlquote

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as django_login
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db.models import Count
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.common import news_service, social_auth
from apps.common.staff_sso import current_staff_label, staff_sso_required, staff_sso_required_json
from asgiref.sync import sync_to_async
from apps.stock import config
from apps.stock.domain.models.stock import MARKET_INFO, MarketCategory
from apps.stock.domain.data.catalog import STOCK_CATALOG
from apps.stock.domain.services import ai_analysis, consent_service, quote_service
from apps.stock.models import ConsentItem, DataQualityLog, LoginHistory, MarketEvent, MemberConsentAgreement, PriceAlert, RecentlyViewedStock, StockMember, StockNewsItem, WatchlistItem

_API_KEY_ATTR = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
_MODEL_ATTR = {
    "anthropic": "ANTHROPIC_MODEL",
    "openai": "OPENAI_MODEL",
    "gemini": "GEMINI_MODEL",
}
# 2026-07-22: aura의 API key 관리 화면과 항목을 통일 -- 사용 토글 + 메모.
_ENABLED_ATTR = {
    "anthropic": "ANTHROPIC_ENABLED",
    "openai": "OPENAI_ENABLED",
    "gemini": "GEMINI_ENABLED",
}
_MEMO_ATTR = {
    "anthropic": "ANTHROPIC_MEMO",
    "openai": "OPENAI_MEMO",
    "gemini": "GEMINI_MEMO",
}


def _parse_market(market_id: str):
    try:
        return MarketCategory[market_id.upper()], None
    except KeyError:
        return None, JsonResponse({"detail": f"Unknown market: {market_id}"}, status=404)


def _masked_provider_key(provider: str) -> str:
    key = ai_analysis._provider_key(provider)
    if not key:
        return ""
    return f"{key[:8]}..." if len(key) > 8 else f"{key}..."


def _decorate_provider_result(result: dict) -> dict:
    provider = result.get("provider")
    if provider:
        result["has_key"] = bool(ai_analysis._provider_key(provider))
        result["masked_key"] = _masked_provider_key(provider)
        result["enabled"] = ai_analysis._provider_enabled(provider)
        result["memo"] = getattr(config, _MEMO_ATTR[provider], "") if provider in _MEMO_ATTR else ""
        if result.get("usable") and not result.get("available_models"):
            result["available_models"] = ai_analysis.list_models(provider)
    return result


def _check_provider_with_models(provider: str) -> dict:
    return _decorate_provider_result(ai_analysis.check_provider(provider))


# --- 정적 자산 (원래 FastAPI의 StaticFiles(directory=...) 마운트 대체) ---

_ASSETS_DIR = __import__("pathlib").Path(__file__).resolve().parent / "assets"


def _index_html(*, is_admin: bool = False) -> str:
    html = (_ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    admin_flag = "true" if is_admin else "false"
    html = html.replace("<body>", f'<body data-stock-admin="{admin_flag}">', 1)
    configured_providers = json.dumps(social_auth.configured_providers())
    html = html.replace(
        '<div id="authBar"></div>',
        f'<div id="authBar"></div><script>window.STOCK_SOCIAL_PROVIDERS = {configured_providers};</script>',
        1,
    )
    if is_admin:
        html = html.replace("<title>AiStockQuote</title>", "<title>AiStockQuote Admin</title>", 1)
        html = html.replace("<h1>AiStockQuote</h1>", "<h1>AiStockQuote Admin</h1>", 1)
        ops_bar = (
            '<div style="display:flex;gap:8px;justify-content:flex-end;'
            'padding:12px 16px;background:#111827;">'
            '<a href="/stock/stock-admin/tests/" '
            'style="color:#fff;background:#059669;padding:8px 12px;'
            'border-radius:8px;text-decoration:none;font-weight:700;">자동테스트 실행 및 결과확인</a>'
            '<a href="/stock/stock-admin/ops/?tab=api" '
            'style="color:#fff;background:#2563eb;padding:8px 12px;'
            'border-radius:8px;text-decoration:none;font-weight:700;">API 테스트</a>'
            '<a href="/stock/stock-admin/ops/?tab=ci" '
            'style="color:#fff;background:#7c3aed;padding:8px 12px;'
            'border-radius:8px;text-decoration:none;font-weight:700;">CI / pytest</a>'
            '<a href="/stock/stock-admin/ops/?tab=cd" '
            'style="color:#fff;background:#374151;padding:8px 12px;'
            'border-radius:8px;text-decoration:none;font-weight:700;">배포 자동화</a>'
            "</div>"
        )
        html = html.replace(f'<body data-stock-admin="{admin_flag}">', f'<body data-stock-admin="{admin_flag}">{ops_bar}', 1)
    return html


def index(request: HttpRequest) -> HttpResponse:
    return HttpResponse(_index_html(is_admin=False), content_type="text/html")


# 2026-07-23: 로그인/회원가입을 index.html의 모달에서 완전히 독립된 페이지로
# 분리(apps/aura_app와 동일 요청, 전체 앱 동일 적용). index.html의
# 나머지 모달(비밀번호 찾기/재설정/변경)은 그대로 남겨뒀다 -- 새 로그인 페이지는
# 인라인 비밀번호 찾기 섹션을 자체적으로 갖고 있어 별도 모달 의존이 없다.
# stock 앱은 Django 템플릿이 아니라 apps/stock/assets/의 원본 HTML을 문자열
# 치환해 서빙하는 구조(_index_html 참고)라, 이 두 페이지도 같은 방식을 따른다.
def _auth_page_html(filename: str) -> str:
    html = (_ASSETS_DIR / filename).read_text(encoding="utf-8")
    configured_providers = json.dumps(social_auth.configured_providers())
    return html.replace(
        "</head>",
        f"<script>window.STOCK_SOCIAL_PROVIDERS = {configured_providers};</script></head>",
        1,
    )


def stock_login_page(request: HttpRequest) -> HttpResponse:
    return HttpResponse(_auth_page_html("login.html"), content_type="text/html")


def stock_signup_page(request: HttpRequest) -> HttpResponse:
    return HttpResponse(_auth_page_html("signup.html"), content_type="text/html")


def stock_admin_login(request: HttpRequest) -> HttpResponse:
    """2026-07-23: 통합 로그인(/staff-login/)으로 리다이렉트만 한다(URL은
    하위 호환으로 살려둠). 기존 Django 세션(레거시 계정)이 이미 있으면 통과."""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("stock_admin")
    return redirect(f"/staff-login/?next={urlquote(request.GET.get('next') or '/stock/stock-admin/')}")


@require_POST
def stock_admin_login_submit(request: HttpRequest) -> HttpResponse:
    """하위 호환용으로만 남겨둔다 -- 새 로그인은 /staff-login/만 쓴다."""
    username = (request.POST.get("username") or "").strip()
    password = request.POST.get("password") or ""
    user = authenticate(request, username=username, password=password)
    if user is not None and user.is_staff:
        django_login(request, user)
        return redirect("stock_admin")
    return render(
        request,
        "stock/admin_login.html",
        {"error": "관리자 계정 정보를 확인해 주세요."},
        status=401,
    )


# 2026-07-23: 통합 SSO(apps/common/staff_sso.py)로 옮겼다 -- 레거시 Django 세션과
# 통합 로그인(/staff-login/) 쿠키 둘 다 인정한다. 아래 호출부는 그대로 두고
# "stock" 앱으로 스코프만 고정한다.
staff_required_json = partial(staff_sso_required_json, app="stock")


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8")), None
    except (UnicodeDecodeError, JSONDecodeError) as error:
        return None, JsonResponse({"ok": False, "error": str(error)}, status=400)


def _stock_social_stats():
    provider_counts = {
        row["social_provider"]: row["count"]
        for row in StockMember.objects.exclude(social_provider__isnull=True)
        .values("social_provider")
        .annotate(count=Count("id"))
    }
    return {
        "total_linked": StockMember.objects.exclude(social_provider__isnull=True).count(),
        "providers": [
            {"provider": code, "label": label, "count": provider_counts.get(code, 0)}
            for code, label in StockMember.SOCIAL_PROVIDER_CHOICES
        ],
    }


def _stock_recent_social_accounts(limit=10):
    members = StockMember.objects.exclude(social_provider__isnull=True).order_by("-social_linked_at")[:limit]
    rows = []
    for member in members:
        last_login = member.login_history.filter(success=True).order_by("-created_at").first()
        rows.append({
            "provider": member.social_provider,
            "social_email": member.social_email or member.email,
            "name": member.name,
            "email": member.email,
            "last_login_at": last_login.created_at.isoformat() if last_login else None,
        })
    return rows


def _stock_signup_path_stats():
    """StockMemberAdmin.changelist_view의 가입경로 통계와 동일한 로직."""
    provider_counts = {
        row["social_provider"]: row["count"]
        for row in StockMember.objects.exclude(social_provider__isnull=True)
        .values("social_provider")
        .annotate(count=Count("id"))
    }
    email_only_count = StockMember.objects.filter(social_provider__isnull=True).count()
    return [{"label": "이메일", "count": email_only_count}] + [
        {"label": label, "count": provider_counts.get(code, 0)}
        for code, label in StockMember.SOCIAL_PROVIDER_CHOICES
    ]


def _stock_member_admin_dict(member) -> dict:
    payload = member.to_public_dict()
    payload["memo"] = member.memo
    payload["loginHistory"] = [
        {
            "success": entry.success,
            "failureReason": entry.failure_reason,
            "ipAddress": entry.ip_address,
            "userAgent": entry.user_agent,
            "createdAt": entry.created_at.isoformat(),
        }
        for entry in member.login_history.order_by("-created_at")[:20]
    ]
    return payload


@ensure_csrf_cookie
@staff_sso_required(app="stock")
def stock_admin(request: HttpRequest) -> HttpResponse:
    """stock 관리자 대시보드.

    2026-07-22: aura_app 관리자 화면(상단바 + 좌측 8탭 단일 화면) 구조로 통일하면서,
    기존에는 공개 스토어프론트 SPA(index.html)를 is_admin 플래그만 바꿔 그대로
    재사용했지만 이제는 별도 Django 템플릿(stock/admin/dashboard.html)을 렌더링한다.
    URL/뷰 이름(stock_admin, /stock/stock-admin/)은 그대로라 로그인 흐름은 안 바뀐다.
    """
    members_payload = {"members": [_stock_member_admin_dict(m) for m in StockMember.objects.all()]}
    from apps.common.member_verification import verification_policy_payload
    return render(
        request,
        "stock/admin/dashboard.html",
        {
            "members_json": json.dumps(members_payload, ensure_ascii=False, indent=2),
            "verification_policy": verification_policy_payload("stock"),
            "signup_path_stats": _stock_signup_path_stats(),
            "active_tab": request.GET.get("tab") or "members",
            "consent_items_json": json.dumps(consent_service.admin_payload(), ensure_ascii=False, indent=2),
            "watchlist_total": WatchlistItem.objects.count(),
            "alert_total": PriceAlert.objects.filter(is_active=True).count(),
            "event_total": MarketEvent.objects.count(),
            "news_total": StockNewsItem.objects.count(),
            "quality_success": DataQualityLog.objects.filter(status="success").count(),
            "quality_failure": DataQualityLog.objects.exclude(status="success").count(),
        },
    )


def consent_items_active(request):
    return JsonResponse(
        {"ok": True, "items": consent_service.public_active_payload()},
        json_dumps_params={"ensure_ascii": False},
    )


def consent_public_page(request, key):
    item = consent_service.get_public_item(key)
    if not item:
        return render(request, "stock/consent_public_page.html", {"item": None, "item_key": key}, status=404)
    return render(request, "stock/consent_public_page.html", {"item": item, "item_key": key})


@staff_required_json
@require_GET
def consent_admin_list(request):
    return JsonResponse(
        {"ok": True, "items": consent_service.admin_payload()},
        json_dumps_params={"ensure_ascii": False},
    )


@staff_required_json
@require_POST
def consent_admin_create_item(request):
    incoming, error = _json_body(request)
    if error:
        return error
    status, data = consent_service.create_item(
        label=incoming.get("label", ""),
        key=incoming.get("key", ""),
        is_required=bool(incoming.get("isRequired", True)),
        sort_order=incoming.get("sortOrder") or 0,
    )
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


@staff_required_json
@require_POST
def consent_admin_update_item(request, key):
    incoming, error = _json_body(request)
    if error:
        return error
    status, data = consent_service.update_item_settings(key, incoming)
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


@staff_required_json
@require_POST
def consent_admin_save_revision(request):
    incoming, error = _json_body(request)
    if error:
        return error
    status, data = consent_service.save_revision(incoming)
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


@staff_required_json
@require_GET
def stock_admin_members_api(request):
    payload = {"members": [_stock_member_admin_dict(m) for m in StockMember.objects.all()]}
    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False})


@staff_required_json
@require_POST
def stock_admin_members_save(request):
    incoming, error = _json_body(request)
    if error:
        return error
    if not isinstance(incoming, dict) or not isinstance(incoming.get("members"), list):
        return JsonResponse({"ok": False, "error": "Members payload must include members list."}, status=400)

    updated = 0
    for entry in incoming.get("members", []):
        if not isinstance(entry, dict):
            continue
        email = (entry.get("email") or "").strip().lower()
        if not email:
            continue
        member = StockMember.objects.filter(email=email).first()
        if not member:
            continue
        member.name = entry.get("name", member.name)
        member.phone = entry.get("phone", member.phone)
        member.postal_code = entry.get("postalCode", member.postal_code)
        member.road_address = entry.get("roadAddress", member.road_address)
        member.address_detail = entry.get("addressDetail", member.address_detail)
        member.role = entry.get("role", member.role)
        member.memo = entry.get("memo", member.memo)
        member.save()
        updated += 1

    return JsonResponse({"ok": True, "updated": updated})


@staff_required_json
@require_POST
def stock_admin_verification_policy_save(request):
    incoming, error = _json_body(request)
    if error:
        return error
    from apps.common.member_verification import save_verification_policy
    policy = save_verification_policy("stock", incoming, updated_by=current_staff_label(request))
    return JsonResponse({"ok": True, "policy": policy})


@staff_required_json
@require_POST
def stock_admin_member_unlink_social(request):
    incoming, error = _json_body(request)
    if error:
        return error
    member_id = (incoming or {}).get("memberId")
    if not member_id:
        return JsonResponse({"ok": False, "error": "memberId is required."}, status=400)
    member = StockMember.objects.filter(id=member_id).first()
    if not member:
        return JsonResponse({"ok": False, "error": "Member not found."}, status=404)
    if not member.social_provider:
        return JsonResponse({"ok": True, "skipped": True, "member": _stock_member_admin_dict(member)})
    member.social_provider = None
    member.social_uid = None
    member.social_email = ""
    member.social_linked_at = None
    member.save(update_fields=["social_provider", "social_uid", "social_email", "social_linked_at"])
    return JsonResponse({"ok": True, "member": _stock_member_admin_dict(member)})


@staff_required_json
@require_POST
def stock_admin_member_verify_resend(request):
    incoming, error = _json_body(request)
    if error:
        return error
    member_id = (incoming or {}).get("memberId")
    if not member_id:
        return JsonResponse({"ok": False, "error": "memberId is required."}, status=400)
    member = StockMember.objects.filter(id=member_id).first()
    if not member:
        return JsonResponse({"ok": False, "error": "Member not found."}, status=404)
    if member.is_email_verified:
        return JsonResponse({"ok": True, "skipped": True, "message": "이미 인증된 계정입니다."})
    token = _generate_email_verification(member)
    status, note = _send_verification_email(request, member, token)
    return JsonResponse({"ok": status == "sent", "status": status, "note": note})


@staff_required_json
@require_POST
def stock_admin_member_password_reset(request):
    incoming, error = _json_body(request)
    if error:
        return error
    member_id = (incoming or {}).get("memberId")
    if not member_id:
        return JsonResponse({"ok": False, "error": "memberId is required."}, status=400)
    member = StockMember.objects.filter(id=member_id).first()
    if not member:
        return JsonResponse({"ok": False, "error": "Member not found."}, status=404)
    token = _generate_password_reset(member)
    status, note = _send_password_reset_email(request, member, token)
    return JsonResponse({"ok": status == "sent", "status": status, "note": note})


def style_css(request: HttpRequest) -> HttpResponse:
    return HttpResponse((_ASSETS_DIR / "style.css").read_text(encoding="utf-8"), content_type="text/css")


def app_js(request: HttpRequest) -> HttpResponse:
    return HttpResponse((_ASSETS_DIR / "app.js").read_text(encoding="utf-8"), content_type="application/javascript")


def auth_js(request: HttpRequest) -> HttpResponse:
    return HttpResponse((_ASSETS_DIR / "auth.js").read_text(encoding="utf-8"), content_type="application/javascript")


# --- API ---


async def _require_stock_admin(request: HttpRequest) -> JsonResponse | None:
    # 2026-07-23, 두 단계에 걸쳐 발견/수정한 버그:
    #
    # 1) "Failed to fetch": 이 함수가 원래 `request.user.is_authenticated`만
    #    직접 확인했는데, `request.user`는 지연 평가되는 SimpleLazyObject라
    #    `.is_authenticated`/`.is_staff`처럼 실제 속성에 처음 접근하는 순간에야
    #    동기 ORM 쿼리(auth_user SELECT)를 실행한다. 그 접근이 async 뷰 코드
    #    안에서 그대로 일어나면 Django가 `SynchronousOnlyOperation`을 던지고,
    #    그 예외가 정상 HTTP 응답을 만들지 못해 브라우저에는 연결이 끊긴
    #    것처럼 보여 fetch()가 "Failed to fetch"로 실패했다. (처음엔
    #    `await sync_to_async(lambda: request.user)()`로만 고치려 했는데, 그
    #    람다는 지연 객체를 "그대로" 반환할 뿐이라 실제 평가는 여전히 바깥
    #    async 컨텍스트에서 일어나 그대로 재현됐다 -- 반드시 sync_to_async로
    #    감싼 함수 "안에서" 속성까지 다 읽어야 한다.)
    #
    # 2) 위 버그를 고친 뒤에도 브라우저 Network 탭에서 302 → Location:
    #    http://errdoc.gabia.net/403.htm(Gabia가 403 응답을 자기 에러 페이지로
    #    가로챔, http라서 mixed content로 또 막힘)이 재현됐다 -- 진짜 원인은
    #    이 함수가 레거시 Django 세션(request.user.is_staff)만 확인하고
    #    통합 SSO(/staff-login/, apps/common/staff_sso.py의 StaffAccount
    #    쿠키)는 전혀 몰랐다는 것. 관리자가 새 통합 로그인으로 들어오면
    #    stock-admin 대시보드 화면 자체는 볼 수 있지만(그 뷰는
    #    `@staff_sso_required`를 써서 통합 SSO를 인식함), 이 함수를 쓰는
    #    AI provider API들은 항상 403을 냈다. `staff_sso.has_access()`(레거시+
    #    통합 SSO 둘 다 인정)로 바꿔서 통일한다 -- DB 쿼리를 포함하므로 (1)과
    #    같은 이유로 반드시 sync_to_async로 감싼다.
    from apps.common import staff_sso

    is_allowed = await sync_to_async(staff_sso.has_access)(request, "stock")

    if is_allowed:
        return None
    return JsonResponse({"detail": "stock 관리자 로그인이 필요합니다."}, status=403)


def _require_stock_admin_sync(request: HttpRequest) -> JsonResponse | None:
    from apps.common import staff_sso

    if staff_sso.has_access(request, "stock"):
        return None
    return JsonResponse({"detail": "stock 관리자 로그인이 필요합니다."}, status=403)


def _method_not_allowed(method: str) -> JsonResponse:
    return JsonResponse({"detail": f"Method {method} not allowed."}, status=405)


def _quote_payload(quote, *, failed=False, period="1mo"):
    payload = quote.model_dump()
    age_seconds = max(0, int(timezone.now().timestamp()) - int(quote.market_time or 0)) if quote.market_time else None
    is_us = (quote.currency or "").upper() == "USD"
    payload["trust"] = {
        "provider": "Yahoo Finance via yfinance",
        "is_delayed": True,
        "delay_note": "거래소별 최소 15분 이상 지연될 수 있으며 실시간 주문용 데이터가 아닙니다.",
        "market_timezone": "America/New_York" if is_us else "Asia/Seoul",
        "reference_at": timezone.datetime.fromtimestamp(quote.market_time, tz=dt_timezone.utc).isoformat() if quote.market_time else None,
        "currency": quote.currency,
        "refresh_status": "failed" if failed else "success",
        "age_seconds": age_seconds,
        "period": period,
    }
    payload["session_prices"] = {"regular": quote.regular_market_price or quote.price, "pre_market": quote.pre_market_price, "after_market": quote.post_market_price}
    payload["krw_conversion"] = {"available": False, "rate": None, "reference_at": None, "note": "환율 공급자 연동 전이므로 원화 환산값을 표시하지 않습니다."} if is_us else {"available": True, "rate": 1, "reference_at": payload["trust"]["reference_at"], "note": "원화 표시 종목"}
    return payload


async def list_markets(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return _method_not_allowed(request.method)

    return JsonResponse(
        [
            {
                "id": market.value,
                "title": MARKET_INFO[market]["title"],
                "description": MARKET_INFO[market]["description"],
                "list_type": "curated_major_stocks",
                "selection_policy": "시가총액·유동성·인지도를 참고한 자체 주요 종목 선정이며 지수 전체 구성종목이 아닙니다.",
                "review_cycle": "분기 1회 및 상장폐지·중대한 시장 변화 발생 시 수시 갱신",
            }
            for market in MarketCategory
        ],
        safe=False,
    )


async def get_market_quotes(request: HttpRequest, market_id: str) -> JsonResponse:
    if request.method != "GET":
        return _method_not_allowed(request.method)

    market, error = _parse_market(market_id)
    if error:
        return error
    refresh = request.GET.get("refresh") in ("1", "true", "True")
    quotes, failed = await quote_service.get_market_quotes(market, force_refresh=refresh)
    now=timezone.now()
    logs=[DataQualityLog(symbol=q.symbol,status="success",is_delayed=True,reference_at=timezone.datetime.fromtimestamp(q.market_time,tz=dt_timezone.utc) if q.market_time else None) for q in quotes]
    logs += [DataQualityLog(symbol=symbol,status="failed",is_delayed=True,reference_at=now,error_message="공급자 응답 누락") for symbol in failed]
    await sync_to_async(DataQualityLog.objects.bulk_create)(logs)
    return JsonResponse(
        {
            "market": market.value,
            "quotes": [_quote_payload(quote) for quote in quotes],
            "failed_symbols": failed,
            "trust": {"provider":"Yahoo Finance via yfinance","refresh_status":"partial_failure" if failed else "success","failed_count":len(failed)},
        }
    )


async def get_quote_detail(request: HttpRequest, symbol: str) -> JsonResponse:
    if request.method != "GET":
        return _method_not_allowed(request.method)

    market_param = request.GET.get("market")
    refresh = request.GET.get("refresh") in ("1", "true", "True")
    period = request.GET.get("period", "1mo")
    if period not in {"1d","5d","1mo","1y","5y"}:
        return JsonResponse({"detail":"period는 1d, 5d, 1mo, 1y, 5y 중 하나여야 합니다."},status=400)
    market_enum = None
    if market_param:
        market_enum, error = _parse_market(market_param)
        if error:
            return error
    try:
        quote = await quote_service.get_quote_detail(
            symbol.strip().upper(), market=market_enum, force_refresh=refresh
            , period=period
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the client as 502
        await sync_to_async(DataQualityLog.objects.create)(symbol=symbol.strip().upper(),status="failed",error_message=str(exc))
        return JsonResponse({"detail": str(exc)}, status=502)
    await sync_to_async(DataQualityLog.objects.create)(symbol=quote.symbol,status="success",reference_at=timezone.datetime.fromtimestamp(quote.market_time,tz=dt_timezone.utc) if quote.market_time else None)
    return JsonResponse(_quote_payload(quote, period=period))


async def get_quote_analysis(request: HttpRequest, symbol: str) -> JsonResponse:
    if request.method != "GET":
        return _method_not_allowed(request.method)

    if not ai_analysis.is_available():
        return JsonResponse({"available": False, "analysis": None})

    market_param = request.GET.get("market")
    market_enum = None
    if market_param:
        market_enum, error = _parse_market(market_param)
        if error:
            return error

    try:
        quote = await quote_service.get_quote_detail(symbol.strip().upper(), market=market_enum)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"detail": str(exc)}, status=502)

    required = [quote.price, quote.previous_close, quote.currency, quote.market_time]
    if any(value is None for value in required) or len(quote.chart_points) < 2:
        return JsonResponse({"available":False,"analysis":None,"blocked":True,"reason":"현재가·전일종가·통화·기준시각·기간 데이터가 모두 확인되어야 AI 분석을 생성합니다."},status=422)
    provider = ai_analysis.get_provider()
    try:
        text = await ai_analysis.analyze_quote(quote)
    except Exception as exc:  # noqa: BLE001 - provider API errors (billing, rate limit, etc.)
        loop = asyncio.get_event_loop()
        available_models = await loop.run_in_executor(None, ai_analysis.list_models, provider)
        return JsonResponse(
            {
                "available": True,
                "analysis": None,
                "provider": provider,
                "error": str(exc),
                "available_models": available_models,
            }
        )
    return JsonResponse({"available": True, "analysis": text, "provider": provider, "evidence": {"symbol":quote.symbol,"price":quote.price,"previous_close":quote.previous_close,"change_percent":quote.change_percent,"currency":quote.currency,"period":"1mo","points":len(quote.chart_points)}, "verified_against_quote": True, "format_version":"stock-analysis-v1"})


@require_GET
def search_stocks(request):
    query=(request.GET.get("q") or "").strip().lower()
    rows=[]
    for market, references in STOCK_CATALOG.items():
        for ref in references:
            if not query or query in ref.symbol.lower() or query in ref.display_name.lower(): rows.append({"symbol":ref.symbol,"name":ref.display_name,"market":market.value})
    unique={row["symbol"]:row for row in rows}
    return JsonResponse({"query":query,"results":list(unique.values())[:100],"catalog_scope":"현재 공급자 조회가 검증된 전체 서버 카탈로그"})


@require_GET
async def compare_stocks(request):
    symbols=[s.strip().upper() for s in (request.GET.get("symbols") or "").split(",") if s.strip()][:3]
    if not 2 <= len(symbols) <= 3:return JsonResponse({"detail":"비교할 종목을 2~3개 지정하세요."},status=400)
    period=request.GET.get("period","1y")
    if period not in {"1mo","1y","5y"}:return JsonResponse({"detail":"비교 기간은 1mo, 1y, 5y입니다."},status=400)
    results=await asyncio.gather(*(quote_service.get_quote_detail(symbol,period=period) for symbol in symbols),return_exceptions=True)
    rows=[]
    for symbol,result in zip(symbols,results):
        if isinstance(result,Exception):rows.append({"symbol":symbol,"error":str(result)});continue
        closes=[p.close for p in result.chart_points]; returns=((closes[-1]/closes[0])-1)*100 if len(closes)>1 and closes[0] else None
        daily=[(closes[i]/closes[i-1])-1 for i in range(1,len(closes)) if closes[i-1]]
        volatility=(sum((x-(sum(daily)/len(daily)))**2 for x in daily)/len(daily))**0.5*100 if daily else None
        rows.append({"symbol":symbol,"name":result.short_name,"return_percent":returns,"daily_volatility_percent":volatility,"market_cap":result.market_cap,"per":result.trailing_pe,"pbr":result.price_to_book,"currency":result.currency,"period":period})
    return JsonResponse({"basis":"동일 공급자·기간·일별 종가 기준","results":rows})


@csrf_exempt
@require_http_methods(["GET","POST","DELETE"])
def watchlist_api(request):
    member=_session_member(request)
    if not member:return JsonResponse({"detail":"로그인이 필요합니다."},status=401)
    if request.method=="GET":return JsonResponse({"items":[{"symbol":x.symbol,"name":x.display_name,"createdAt":x.created_at.isoformat()} for x in member.watchlist.all()]})
    incoming,error=_json_body(request)
    if error:return error
    symbol=(incoming.get("symbol") or "").strip().upper()
    if request.method=="DELETE":member.watchlist.filter(symbol=symbol).delete();return JsonResponse({"ok":True})
    item,_=WatchlistItem.objects.update_or_create(member=member,symbol=symbol,defaults={"display_name":incoming.get("name","")})
    return JsonResponse({"ok":True,"symbol":item.symbol},status=201)


@csrf_exempt
@require_http_methods(["GET","POST"])
def alerts_api(request):
    member=_session_member(request)
    if not member:return JsonResponse({"detail":"로그인이 필요합니다."},status=401)
    if request.method=="GET":return JsonResponse({"alerts":[{"id":x.pk,"symbol":x.symbol,"condition":x.condition,"threshold":float(x.threshold),"active":x.is_active} for x in member.price_alerts.all()]})
    incoming,error=_json_body(request)
    if error:return error
    item=PriceAlert.objects.create(member=member,symbol=(incoming.get("symbol") or "").upper(),condition=incoming.get("condition","above"),threshold=incoming.get("threshold",0))
    return JsonResponse({"ok":True,"id":item.pk},status=201)


@require_GET
def recent_stocks_api(request):
    member=_session_member(request)
    if not member:return JsonResponse({"detail":"로그인이 필요합니다."},status=401)
    return JsonResponse({"items":[{"symbol":x.symbol,"viewedAt":x.viewed_at.isoformat()} for x in member.recent_stocks.all()[:20]]})


@csrf_exempt
@require_POST
def record_recent_stock(request):
    member=_session_member(request)
    if not member:return JsonResponse({"detail":"로그인이 필요합니다."},status=401)
    incoming,error=_json_body(request)
    if error:return error
    item,_=RecentlyViewedStock.objects.update_or_create(member=member,symbol=(incoming.get("symbol") or "").upper())
    return JsonResponse({"ok":True,"viewedAt":item.viewed_at.isoformat()})


@require_GET
def stock_context(request, symbol):
    events=[{"type":x.event_type,"title":x.title,"at":x.event_at.isoformat(),"source":{"name":x.source_name,"url":x.source_url},"estimated":x.is_estimated} for x in MarketEvent.objects.filter(symbol=symbol.upper()).order_by("event_at")[:20]]
    news=[{"title":x.title,"publishedAt":x.published_at.isoformat(),"source":{"name":x.source_name,"url":x.source_url},"factSummary":x.fact_summary,"marketInterpretation":x.market_interpretation} for x in StockNewsItem.objects.filter(symbol=symbol.upper()).order_by("-published_at")[:20]]
    return JsonResponse({"symbol":symbol.upper(),"events":events,"news":news,"help":{"PER":"주가를 주당순이익으로 나눈 값이며 업종·일회성 이익에 따라 왜곡될 수 있습니다.","PBR":"주가를 주당순자산으로 나눈 값이며 무형자산 중심 기업 비교에는 한계가 있습니다.","volume":"거래량 증가는 관심 증가를 뜻할 수 있지만 방향을 단독으로 설명하지 못합니다."}},json_dumps_params={"ensure_ascii":False})


async def _check_provider_bounded(provider: str) -> dict:
    loop = asyncio.get_event_loop()
    hard_timeout = config.AI_REQUEST_TIMEOUT_SECONDS + 5
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _check_provider_with_models, provider),
            timeout=hard_timeout,
        )
        return result
    except asyncio.TimeoutError:
        return _decorate_provider_result({
            "provider": provider,
            "configured": bool(ai_analysis._provider_key(provider)),
            "model": ai_analysis._configured_model(provider),
            "usable": False,
            "error": f"응답이 {hard_timeout}초 내에 오지 않았습니다 (네트워크 연결을 확인하세요).",
            "available_models": [],
        })


async def get_ai_status(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return _method_not_allowed(request.method)

    forbidden = await _require_stock_admin(request)
    if forbidden:
        return forbidden

    results = await asyncio.gather(
        *(_check_provider_bounded(p) for p in ai_analysis._PROVIDER_ORDER)
    )
    active_provider = ai_analysis.get_provider()
    for r in results:
        r["is_active"] = r["provider"] == active_provider

    return JsonResponse(
        {
            "providers": list(results),
            "active_provider": active_provider,
            "ai_provider_override": config.AI_PROVIDER,
        }
    )


async def update_ai_provider_config(request: HttpRequest, provider: str) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed(request.method)

    forbidden = await _require_stock_admin(request)
    if forbidden:
        return forbidden

    if provider not in ai_analysis._PROVIDER_ORDER:
        return JsonResponse({"detail": f"Unknown provider: {provider}"}, status=404)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    api_key = (body.get("api_key") or "").strip() or None
    model = (body.get("model") or "").strip() or None
    persisted = False

    if api_key:
        key_attr = _API_KEY_ATTR[provider]
        setattr(config, key_attr, api_key)
        config.persist_env_value(key_attr, api_key)
        persisted = True

    if model:
        model_attr = _MODEL_ATTR[provider]
        setattr(config, model_attr, model)
        config.persist_env_value(model_attr, model)
        persisted = True

    # 2026-07-22: aura와 항목 통일 -- "사용" 토글과 메모. 둘 다 body에 키가
    # 있을 때만(None이 아닐 때만) 갱신한다 -- "키 검증" 버튼처럼 빈 body({})로
    # 이 엔드포인트를 호출해도 기존 사용/메모 값이 실수로 지워지지 않도록.
    if "enabled" in body:
        enabled_attr = _ENABLED_ATTR[provider]
        enabled_value = bool(body.get("enabled"))
        setattr(config, enabled_attr, enabled_value)
        config.persist_env_value(enabled_attr, "1" if enabled_value else "0")
        persisted = True

    if "memo" in body:
        memo_attr = _MEMO_ATTR[provider]
        memo_value = (body.get("memo") or "").strip()
        setattr(config, memo_attr, memo_value)
        config.persist_env_value(memo_attr, memo_value)
        persisted = True

    ai_analysis.reset_client_cache()

    result = await _check_provider_bounded(provider)
    result["persisted_to_env"] = persisted
    return JsonResponse(result)


async def set_active_provider(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed(request.method)

    forbidden = await _require_stock_admin(request)
    if forbidden:
        return forbidden

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    provider = (body.get("provider") or "").strip().lower() or None
    if provider is not None and provider not in ai_analysis._PROVIDER_ORDER:
        return JsonResponse({"detail": f"Unknown provider: {provider}"}, status=404)
    if provider is not None and not ai_analysis._provider_enabled(provider):
        return JsonResponse(
            {"detail": "사용 꺼짐 상태인 provider는 활성 provider로 설정할 수 없습니다. 먼저 사용을 켜 주세요."},
            status=400,
        )

    config.AI_PROVIDER = provider
    config.persist_env_value("AI_PROVIDER", provider or "")
    ai_analysis.reset_client_cache()

    return await get_ai_status(request)


# --- 주식뉴스 메뉴 (2026-07-22 신설, GNews API) -------------------------------
#
# 사용자 화면에 새로 배치하는 "주식뉴스" 카드 목록. AI 공급자 설정과 마찬가지로
# GNews 호출 자체는 동기(requests) 라이브러리라 async view 안에서는
# run_in_executor로 감싼다(ai_analysis.analyze_quote와 동일한 이유 -- 블로킹
# 호출이 이벤트 루프를 막지 않게 하기 위함). API key 저장/검증은 관리자 전용이라
# _require_stock_admin으로 막고, 뉴스 조회 자체(stock_news_api)는 일반 사용자
# 화면에서 쓰는 것이므로 로그인/관리자 여부를 요구하지 않는다.

STOCK_NEWS_QUERY = '주식 OR 증시 OR 코스피 OR 코스닥 OR "주식시장"'


async def stock_news_api(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return _method_not_allowed(request.method)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: news_service.fetch_news(STOCK_NEWS_QUERY, lang="ko", max_results=12, cache_key="stock_news"),
    )
    return JsonResponse(result, json_dumps_params={"ensure_ascii": False})


async def stock_news_config_api(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed(request.method)

    forbidden = await _require_stock_admin(request)
    if forbidden:
        return forbidden

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    api_key = (body.get("api_key") or "").strip()
    if api_key:
        news_service.save_api_key(api_key)
        news_service.clear_cache()

    return JsonResponse({"ok": True, "provider": news_service.status_payload()})


async def stock_news_validate_api(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed(request.method)

    forbidden = await _require_stock_admin(request)
    if forbidden:
        return forbidden

    loop = asyncio.get_event_loop()
    is_valid, message = await loop.run_in_executor(None, news_service.validate_api_key)
    return JsonResponse(
        {"ok": True, "valid": is_valid, "message": message, "provider": news_service.status_payload()}
    )


# --- 소셜 로그인(카카오/네이버/구글/애플) 관리 — 5개 서브앱 공용 --------------------
#
# AI 공급자 설정과 달리 서버가 대신 "핑"으로 검증할 수 없다(OAuth 인가 코드
# 흐름은 브라우저 리다이렉트가 필요해서 access_key처럼 1회 API 호출로 유효성을
# 확인할 방법이 없다). 그래서 이 두 엔드포인트는 configured 여부(Client ID
# 존재)만 보고하고, "실제로 되는지"는 화면에서 실제 로그인 URL을 새 탭으로 여는
# 방식으로 사람이 직접 확인하게 한다 — get_ai_status/update_ai_provider_config의
# usable/check_provider 같은 자동 검증은 정직하게 흉내내지 않는다.
# 동기(sync) 뷰다 — 위 AI 엔드포인트들과 달리 외부 API를 부르지 않아 async로 할
# 이유가 없다. Django는 같은 URLconf 안에 동기/비동기 뷰를 섞어도 문제없다.

def get_social_login_status(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return _method_not_allowed(request.method)
    forbidden = _require_stock_admin_sync(request)
    if forbidden:
        return forbidden
    providers = social_auth.credential_status()
    for row in providers:
        row["default_redirect_uri"] = request.build_absolute_uri(
            reverse("stock_auth_social_callback", args=[row["provider"]])
        )
    return JsonResponse({
        "providers": providers,
        "stats": _stock_social_stats(),
        "recent_accounts": _stock_recent_social_accounts(),
    })


def update_social_login_config(request: HttpRequest, provider: str) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed(request.method)
    forbidden = _require_stock_admin_sync(request)
    if forbidden:
        return forbidden
    if provider not in social_auth.PROVIDERS:
        return JsonResponse({"detail": f"Unknown provider: {provider}"}, status=404)

    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError as error:
        return JsonResponse({"detail": str(error)}, status=400)

    # 2026-07-22: LinguaUp 백오피스 형태로 소셜로그인 탭을 개편하면서 필드가
    # client_id/client_secret 2개에서 늘었다 -- 텍스트 필드는 body에 키가 있을
    # 때만(None이 아닐 때만) 갱신하고, is_enabled는 불리언으로 별도 처리한다.
    text_fields = ["client_id", "client_secret", "redirect_uri", "scope"]
    if provider == "apple":
        text_fields += ["apple_team_id", "apple_key_id", "apple_private_key"]

    persisted = False
    for field in text_fields:
        if field in body:
            social_auth.persist_credential(provider, field, (body.get(field) or "").strip() or None)
            persisted = True
    if "is_enabled" in body:
        social_auth.persist_credential(provider, "is_enabled", bool(body.get("is_enabled")))
        persisted = True

    rows = social_auth.credential_status()
    result = next((r for r in rows if r["provider"] == provider), None)
    result = dict(result or {})
    result["persisted_to_env"] = persisted
    result["default_redirect_uri"] = request.build_absolute_uri(
        reverse("stock_auth_social_callback", args=[provider])
    )
    return JsonResponse(result)


# --- 회원 인증 (2026-07 신규) ---
# apps/aura_app/views.py의 회원가입/로그인/비밀번호 찾기 구현과 동일한 패턴입니다.
# 세션 키만 "aura_member_id" 대신 "stock_member_id"로 분리해 두 앱의 로그인 상태가
# 서로 섞이지 않게 했습니다 (사용자 요청: 사이트별 회원 DB 완전 분리).

EMAIL_VERIFICATION_TOKEN_TTL_HOURS = 24
PASSWORD_RESET_TOKEN_TTL_HOURS = 1

PASSWORD_MIN_LENGTH = 8
_PASSWORD_LETTER_RE = re.compile(r"[A-Za-z]")
_PASSWORD_DIGIT_RE = re.compile(r"[0-9]")
_PASSWORD_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _password_policy_error(password):
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"비밀번호는 {PASSWORD_MIN_LENGTH}자 이상이어야 합니다."
    if not _PASSWORD_LETTER_RE.search(password):
        return "비밀번호에 영문자를 포함해야 합니다."
    if not _PASSWORD_DIGIT_RE.search(password):
        return "비밀번호에 숫자를 포함해야 합니다."
    if not _PASSWORD_SPECIAL_RE.search(password):
        return "비밀번호에 특수문자를 포함해야 합니다."
    return None


def _validate_consents(consents: dict):
    """게시된(is_published=True) 필수 항목 중 체크되지 않은 첫 항목의 라벨을 반환한다.
    (apps/aura_app/domain/services/member_service.py의 validate_consents와 동일 패턴 --
    stock에는 별도 member_service.py가 없어 views.py에 직접 둔다.)"""
    for item in ConsentItem.objects.filter(is_published=True, is_required=True).order_by("sort_order", "key"):
        if not consents.get(item.key):
            return item.label
    return None


def _record_consents(member_id: str, consents: dict) -> None:
    for item in ConsentItem.objects.filter(is_published=True):
        if not consents.get(item.key):
            continue
        revision = item.active_revision
        if not revision:
            continue
        MemberConsentAgreement.objects.create(member_id=member_id, item_key=item.key, version=revision.version)


def _session_member(request):
    member_id = request.session.get("stock_member_id")
    if not member_id:
        return None
    return StockMember.objects.filter(id=member_id).first()


def _client_ip(request):
    """nginx 리버스 프록시 뒤(config/settings.py SECURE_PROXY_SSL_HEADER 참고)라
    X-Forwarded-For의 첫 값을 우선 쓰고 없으면 REMOTE_ADDR로 폴백한다."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _record_login_attempt(request, *, member, attempted_email, success, failure_reason=""):
    LoginHistory.objects.create(
        member=member,
        attempted_email=attempted_email,
        success=success,
        failure_reason=failure_reason,
        ip_address=_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )


# 로그인 실패 5회/15분 잠금 정책(apps/aura_app/views.py의 동일 함수와 같은 패턴 --
# 개인정보보호법 시행령 제30조 안전성 확보조치 대응). 이메일 기준과 IP 기준을 모두
# 검사하고, 잘못된 비밀번호(invalid_credentials) 시도만 잠금 판정에 반영한다.
LOGIN_LOCKOUT_THRESHOLD = 5
LOGIN_LOCKOUT_WINDOW_MINUTES = 15


def _login_lockout_error(request, email):
    window_start = timezone.now() - timedelta(minutes=LOGIN_LOCKOUT_WINDOW_MINUTES)
    recent_failures = LoginHistory.objects.filter(
        success=False,
        failure_reason="invalid_credentials",
        created_at__gte=window_start,
    )
    email_failures = recent_failures.filter(attempted_email=email).count()
    ip_failures = recent_failures.filter(ip_address=_client_ip(request)).count()
    if email_failures >= LOGIN_LOCKOUT_THRESHOLD or ip_failures >= LOGIN_LOCKOUT_THRESHOLD:
        return JsonResponse(
            {
                "ok": False,
                "error": f"로그인 시도가 너무 많습니다. {LOGIN_LOCKOUT_WINDOW_MINUTES}분 후 다시 시도해 주세요.",
            },
            status=429,
        )
    return None


def _send_member_email(recipient, subject, message):
    """Send a real email via the configured SMTP backend (settings.EMAIL_*)."""
    if not django_settings.EMAIL_HOST_USER or not django_settings.EMAIL_HOST_PASSWORD:
        return (
            "failed",
            "이메일 계정 정보(EMAIL_HOST_USER / EMAIL_HOST_PASSWORD)가 설정되지 않았습니다. "
            ".env를 확인해 주세요.",
        )
    try:
        send_mail(
            subject or "AiStockQuote 안내",
            message,
            django_settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
    except (smtplib.SMTPException, OSError) as error:
        return "failed", f"이메일 발송 실패: {error}"
    return "sent", f"{recipient} 앞으로 이메일을 발송했습니다."


def _generate_email_verification(member):
    token = secrets.token_urlsafe(32)
    member.email_verification_token = token
    member.email_verification_expires_at = timezone.now() + timedelta(
        hours=EMAIL_VERIFICATION_TOKEN_TTL_HOURS
    )
    member.save(update_fields=["email_verification_token", "email_verification_expires_at"])
    return token


def _generate_password_reset(member):
    token = secrets.token_urlsafe(32)
    member.password_reset_token = token
    member.password_reset_expires_at = timezone.now() + timedelta(
        hours=PASSWORD_RESET_TOKEN_TTL_HOURS
    )
    member.save(update_fields=["password_reset_token", "password_reset_expires_at"])
    return token


def _send_verification_email(request, member, token):
    verify_url = request.build_absolute_uri(f"{reverse('stock_email_verify')}?token={token}")
    subject = "[AiStockQuote] 이메일 인증을 완료해 주세요"
    message = (
        f"{member.name}님, AiStockQuote 회원가입을 완료하려면 아래 링크에서 이메일 인증을 완료해 주세요.\n"
        f"(유효시간 {EMAIL_VERIFICATION_TOKEN_TTL_HOURS}시간)\n\n"
        f"{verify_url}\n"
    )
    return _send_member_email(member.email, subject, message)


def _send_password_reset_email(request, member, token):
    reset_url = f"{request.build_absolute_uri('/stock/')}?resetToken={token}"
    subject = "[AiStockQuote] 비밀번호 재설정 안내"
    message = (
        f"{member.name}님, 아래 링크에서 새 비밀번호를 설정해 주세요.\n"
        f"(유효시간 {PASSWORD_RESET_TOKEN_TTL_HOURS}시간, 본인이 요청하지 않았다면 이 메일을 무시하세요.)\n\n"
        f"{reset_url}\n"
    )
    return _send_member_email(member.email, subject, message)


def _verification_result_page(*, ok, title, message_text):
    status_class = "ok" if ok else "error"
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, "Noto Sans KR", sans-serif; background:#0f1115; color:#f5f5f7;
         display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:24px; }}
  .card {{ max-width:420px; text-align:center; }}
  h1 {{ font-size:1.3rem; margin-bottom:12px; }}
  p {{ line-height:1.6; color:#c7c9d1; margin:6px 0; }}
  a.button {{ display:inline-block; margin-top:22px; padding:10px 22px; border-radius:999px;
              background:#417690; color:#fff; text-decoration:none; font-weight:600; }}
  .status-error h1 {{ color:#ff8a8a; }}
</style>
</head>
<body>
  <div class="card status-{status_class}">
    <h1>{title}</h1>
    <p>{message_text}</p>
    <a class="button" href="/stock/">AiStockQuote로 돌아가기</a>
  </div>
</body>
</html>"""
    return HttpResponse(html, status=200 if ok else 400)


@require_GET
def stock_email_verify(request):
    token = (request.GET.get("token") or "").strip()
    if not token:
        return _verification_result_page(
            ok=False,
            title="인증 링크가 올바르지 않습니다",
            message_text="토큰이 없습니다. 가입 시 받은 이메일의 링크를 다시 확인해 주세요.",
        )

    member = StockMember.objects.filter(email_verification_token=token).first()
    if not member:
        return _verification_result_page(
            ok=False,
            title="인증 링크가 올바르지 않습니다",
            message_text="유효하지 않거나 이미 사용된 링크입니다.",
        )

    if member.is_email_verified:
        return _verification_result_page(
            ok=True,
            title="이미 인증된 계정입니다",
            message_text="이미 이메일 인증이 완료되었습니다. 바로 로그인하실 수 있습니다.",
        )

    if not member.email_verification_expires_at or member.email_verification_expires_at < timezone.now():
        return _verification_result_page(
            ok=False,
            title="인증 링크가 만료되었습니다",
            message_text="로그인 화면에서 인증 메일을 다시 요청해 주세요.",
        )

    member.is_email_verified = True
    member.email_verification_token = None
    member.email_verification_expires_at = None
    member.save(
        update_fields=["is_email_verified", "email_verification_token", "email_verification_expires_at"]
    )

    return _verification_result_page(
        ok=True,
        title="이메일 인증이 완료되었습니다",
        message_text="이제 AiStockQuote에 로그인하실 수 있습니다.",
    )


@require_GET
def stock_auth_me(request):
    member = _session_member(request)
    return JsonResponse(
        {"ok": True, "authenticated": bool(member), "member": member.to_public_dict() if member else None},
        json_dumps_params={"ensure_ascii": False},
    )


@csrf_exempt
@require_POST
def stock_auth_signup(request):
    try:
        incoming = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    email = (incoming.get("email") or "").strip().lower()
    name = (incoming.get("name") or "").strip()
    password = incoming.get("password", "")
    password_confirm = incoming.get("passwordConfirm")
    # 2026-07-22: "개인정보 수집·이용 동의"(privacyConsentAccepted) 단일 필드는
    # ConsentItem 체계의 "개인정보처리방침" 항목으로 흡수됐다.
    consents = incoming.get("consents") or {}

    if not email or not _EMAIL_RE.match(email) or not name or not password:
        return JsonResponse({"ok": False, "error": "이름, 이메일, 비밀번호를 확인해 주세요."}, status=400)

    if password != password_confirm:
        return JsonResponse({"ok": False, "error": "비밀번호가 일치하지 않습니다."}, status=400)

    missing_consent_label = _validate_consents(consents)
    if missing_consent_label:
        return JsonResponse({"ok": False, "error": f"{missing_consent_label} 동의가 필요합니다."}, status=400)

    password_error = _password_policy_error(password)
    if password_error:
        return JsonResponse({"ok": False, "error": password_error}, status=400)

    if StockMember.objects.filter(email=email).exists():
        return JsonResponse({"ok": False, "error": "이미 등록된 이메일입니다."}, status=409)

    from apps.common.member_verification import get_verification_policy
    verification_policy = get_verification_policy("stock")
    phone = (incoming.get("phone") or "").strip()
    road_address = (incoming.get("roadAddress") or "").strip()
    if verification_policy.require_phone and not phone:
        return JsonResponse({"ok": False, "error": "휴대전화번호를 입력해 주세요."}, status=400)
    if verification_policy.require_address and not road_address:
        return JsonResponse({"ok": False, "error": "주소를 입력해 주세요."}, status=400)
    privacy_policy_checked = bool(consents.get("privacy-policy"))
    member = StockMember.objects.create(
        email=email,
        name=name,
        password_hash=make_password(password),
        phone=phone,
        postal_code=(incoming.get("postalCode") or "").strip(),
        road_address=road_address,
        address_detail=(incoming.get("addressDetail") or "").strip(),
        privacy_consent_accepted=privacy_policy_checked,
        privacy_consent_accepted_at=timezone.now() if privacy_policy_checked else None,
    )
    _record_consents(member.id, consents)

    email_status, email_note = "disabled", "관리자 설정에 따라 이메일 인증을 생략했습니다."
    if verification_policy.email_enabled:
        token = _generate_email_verification(member)
        email_status, email_note = _send_verification_email(request, member, token)
    else:
        member.is_email_verified = True
        member.save(update_fields=["is_email_verified"])

    return JsonResponse(
        {
            "ok": True,
            "pendingVerification": verification_policy.email_enabled or verification_policy.phone_enabled,
            "member": member.to_public_dict(),
            "emailStatus": email_status,
            "emailNote": email_note,
        },
        json_dumps_params={"ensure_ascii": False},
    )


@csrf_exempt
@require_POST
def stock_auth_login(request):
    try:
        incoming = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    email = (incoming.get("email") or "").strip().lower()
    password = incoming.get("password", "")

    lockout_error = _login_lockout_error(request, email)
    if lockout_error:
        return lockout_error

    member = StockMember.objects.filter(email=email).first()

    if not member or not member.password_hash or not check_password(password, member.password_hash):
        _record_login_attempt(
            request, member=member, attempted_email=email, success=False, failure_reason="invalid_credentials"
        )
        return JsonResponse({"ok": False, "error": "로그인 정보를 확인해 주세요."}, status=401)

    if not member.is_email_verified:
        _record_login_attempt(
            request, member=member, attempted_email=email, success=False, failure_reason="email_not_verified"
        )
        return JsonResponse(
            {
                "ok": False,
                "error": "이메일 인증이 필요합니다. 받은 편지함에서 인증 링크를 확인해 주세요.",
                "needsVerification": True,
            },
            status=403,
        )

    request.session["stock_member_id"] = member.id
    _record_login_attempt(request, member=member, attempted_email=email, success=True)
    return JsonResponse({"ok": True, "member": member.to_public_dict()}, json_dumps_params={"ensure_ascii": False})


def _safe_stock_next(value):
    if value and value.startswith("/stock/"):
        return value
    return "/stock/"


def _social_login(request, profile, *, consents=None):
    """소셜 프로필로 로그인하거나 새로 가입한다.

    stock에는 별도 domain/services/member_service.py가 없이 인증 로직이 전부 이
    파일에 있으므로(_generate_email_verification 등과 같은 패턴), 소셜 로그인도
    같은 방식으로 뷰 파일에 헬퍼 함수로 둔다. 2026-07-22: privacy_consent_accepted
    단일 플래그 대신 ConsentItem 기반 consents dict로 필수 동의를 검증한다.
    """
    consents = consents or {}
    if not profile.uid:
        return 400, {"ok": False, "error": "소셜 로그인 공급자로부터 사용자 정보를 받지 못했습니다."}

    member = StockMember.objects.filter(
        social_provider=profile.provider, social_uid=profile.uid
    ).first()

    linked_now = False
    if not member and profile.email:
        existing = StockMember.objects.filter(email=profile.email.strip().lower()).first()
        if existing and not existing.social_provider:
            existing.social_provider = profile.provider
            existing.social_uid = profile.uid
            existing.social_email = profile.email
            existing.social_linked_at = timezone.now()
            existing.save(
                update_fields=["social_provider", "social_uid", "social_email", "social_linked_at"]
            )
            member = existing
            linked_now = True

    if not member:
        missing_consent_label = _validate_consents(consents)
        if missing_consent_label:
            return 400, {
                "ok": False,
                "error": f"{missing_consent_label} 동의가 필요합니다. 회원가입 화면에서 동의한 뒤 소셜 버튼을 눌러주세요.",
            }
        if not profile.email:
            provider_label = social_auth.PROVIDER_LABELS.get(profile.provider, profile.provider)
            return 400, {
                "ok": False,
                "error": f"{provider_label} 계정에서 이메일 제공에 동의해야 가입할 수 있습니다.",
            }

        privacy_policy_checked = bool(consents.get("privacy-policy"))
        member = StockMember.objects.create(
            email=profile.email.strip().lower(),
            name=(profile.name or profile.email.split("@")[0]).strip(),
            password_hash=make_password(secrets.token_urlsafe(32)),
            memo=f"{social_auth.PROVIDER_LABELS.get(profile.provider, profile.provider)} 소셜 가입",
            is_email_verified=True,
            social_provider=profile.provider,
            social_uid=profile.uid,
            social_email=profile.email,
            social_linked_at=timezone.now(),
            privacy_consent_accepted=privacy_policy_checked,
            privacy_consent_accepted_at=timezone.now() if privacy_policy_checked else None,
        )
        _record_consents(member.id, consents)
        linked_now = True

    if not member.is_email_verified and profile.email:
        member.is_email_verified = True
        member.save(update_fields=["is_email_verified"])

    request.session["stock_member_id"] = member.id
    _record_login_attempt(request, member=member, attempted_email=member.email, success=True)
    return 200, {"ok": True, "member": member.to_public_dict(), "linked": linked_now}


@require_GET
def stock_auth_social_start(request, provider):
    if provider not in social_auth.PROVIDERS:
        raise Http404("Unknown provider")
    if not social_auth.is_configured(provider):
        return redirect("/stock/?socialError=not_configured")

    redirect_uri = social_auth.effective_redirect_uri(
        provider, request.build_absolute_uri(reverse("stock_auth_social_callback", args=[provider]))
    )
    try:
        consents = json.loads(request.GET.get("consents") or "{}")
        if not isinstance(consents, dict):
            consents = {}
    except JSONDecodeError:
        consents = {}
    state = social_auth.sign_state(
        {
            "next": _safe_stock_next(request.GET.get("next")),
            "consents": consents,
        }
    )
    try:
        target = social_auth.authorize_url(provider, redirect_uri, state, scope=social_auth.scope_override(provider))
    except social_auth.SocialAuthError as exc:
        return redirect(f"/stock/?socialError={urlquote(str(exc))}")
    return redirect(target)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def stock_auth_social_callback(request, provider):
    if provider not in social_auth.PROVIDERS:
        raise Http404("Unknown provider")

    params = request.POST if request.method == "POST" else request.GET

    try:
        state = social_auth.unsign_state(params.get("state", ""))
    except social_auth.SocialAuthError:
        return redirect("/stock/?socialError=invalid_state")

    next_path = _safe_stock_next(state.get("next"))

    if params.get("error"):
        return redirect(f"{next_path}?socialError=provider_denied")

    try:
        if provider == "apple":
            profile = social_auth.verify_apple_id_token(params.get("id_token", ""))
            if not profile.name:
                raw_user = params.get("user", "")
                if raw_user:
                    try:
                        name_obj = (json.loads(raw_user) or {}).get("name") or {}
                        profile.name = " ".join(
                            part for part in [name_obj.get("firstName"), name_obj.get("lastName")] if part
                        ).strip()
                    except (ValueError, TypeError):
                        pass
        else:
            redirect_uri = social_auth.effective_redirect_uri(
                provider, request.build_absolute_uri(reverse("stock_auth_social_callback", args=[provider]))
            )
            token_response = social_auth.exchange_code(provider, params.get("code", ""), redirect_uri)
            profile = social_auth.fetch_profile(provider, token_response)
    except social_auth.SocialAuthError as exc:
        return redirect(f"{next_path}?socialError={urlquote(str(exc))}")

    status, data = _social_login(request, profile, consents=state.get("consents") or {})
    if status != 200:
        return redirect(f"{next_path}?socialError={urlquote(data.get('error', ''))}")

    return redirect(f"{next_path}?social=success")


@csrf_exempt
@require_POST
def stock_auth_logout(request):
    request.session.pop("stock_member_id", None)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def stock_auth_withdraw(request):
    """회원 탈퇴(계정 삭제, 즉시 비식별화). apps/aura_app/views.py의 auth_withdraw와
    동일한 패턴 -- 현재 비밀번호 재확인 후 StockMember 행을 삭제한다. LoginHistory는
    member가 SET_NULL FK라 회원 연결만 끊어지고 접속기록 자체는 그대로 남는다."""
    member = _session_member(request)
    if not member:
        return JsonResponse({"ok": False, "error": "로그인이 필요합니다."}, status=401)

    try:
        incoming = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    password = incoming.get("password", "")
    if not member.password_hash or not check_password(password, member.password_hash):
        return JsonResponse({"ok": False, "error": "비밀번호가 올바르지 않습니다."}, status=400)

    member.delete()
    request.session.pop("stock_member_id", None)

    return JsonResponse(
        {"ok": True, "message": "회원 탈퇴가 완료되었습니다."},
        json_dumps_params={"ensure_ascii": False},
    )


@csrf_exempt
@require_POST
def stock_auth_resend_verification(request):
    try:
        incoming = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    email = (incoming.get("email") or "").strip().lower()
    generic_response = {"ok": True, "message": "해당 이메일이 등록되어 있다면 인증 메일을 다시 보냈습니다."}

    member = StockMember.objects.filter(email=email).first() if email else None
    if not member or member.is_email_verified:
        return JsonResponse(generic_response, json_dumps_params={"ensure_ascii": False})

    token = _generate_email_verification(member)
    _send_verification_email(request, member, token)
    return JsonResponse(generic_response, json_dumps_params={"ensure_ascii": False})


@csrf_exempt
@require_POST
def stock_auth_forgot_password(request):
    try:
        incoming = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    email = (incoming.get("email") or "").strip().lower()
    generic_response = {"ok": True, "message": "해당 이메일이 등록되어 있다면 비밀번호 재설정 메일을 보냈습니다."}

    member = StockMember.objects.filter(email=email).first() if email else None
    if not member:
        return JsonResponse(generic_response, json_dumps_params={"ensure_ascii": False})

    token = _generate_password_reset(member)
    _send_password_reset_email(request, member, token)
    return JsonResponse(generic_response, json_dumps_params={"ensure_ascii": False})


@csrf_exempt
@require_POST
def stock_auth_reset_password(request):
    try:
        incoming = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    token = (incoming.get("token") or "").strip()
    password = incoming.get("password", "")
    password_confirm = incoming.get("passwordConfirm")

    if not token:
        return JsonResponse(
            {"ok": False, "error": "재설정 링크가 올바르지 않습니다. 이메일의 링크를 다시 확인해 주세요."},
            status=400,
        )

    member = StockMember.objects.filter(password_reset_token=token).first()
    if not member:
        return JsonResponse({"ok": False, "error": "재설정 링크가 올바르지 않거나 이미 사용되었습니다."}, status=400)

    if not member.password_reset_expires_at or member.password_reset_expires_at < timezone.now():
        return JsonResponse({"ok": False, "error": "재설정 링크가 만료되었습니다. 비밀번호 찾기를 다시 시도해 주세요."}, status=400)

    if password_confirm is not None and password != password_confirm:
        return JsonResponse({"ok": False, "error": "비밀번호가 일치하지 않습니다."}, status=400)

    password_error = _password_policy_error(password)
    if password_error:
        return JsonResponse({"ok": False, "error": password_error}, status=400)

    member.password_hash = make_password(password)
    member.password_reset_token = None
    member.password_reset_expires_at = None
    member.save(update_fields=["password_hash", "password_reset_token", "password_reset_expires_at"])

    return JsonResponse(
        {"ok": True, "message": "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해 주세요."},
        json_dumps_params={"ensure_ascii": False},
    )


@csrf_exempt
@require_POST
def stock_auth_change_password(request):
    """로그인 상태에서 현재 비밀번호를 확인하고 새 비밀번호로 바꾸는, 비밀번호 찾기와
    별개의 자기 서비스 기능. 비밀번호 찾기(reset)는 이메일 링크의 1회용 토큰으로
    본인 확인을 대신하지만, 이건 이미 로그인된 사람이 스스로 바꾸는 것이라
    현재 비밀번호 확인을 추가로 요구한다(세션 탈취만으로 비밀번호를 못 바꾸게).
    """
    member = _session_member(request)
    if not member:
        return JsonResponse({"ok": False, "error": "로그인이 필요합니다."}, status=401)

    try:
        incoming = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    current_password = incoming.get("currentPassword", "")
    new_password = incoming.get("newPassword", "")
    new_password_confirm = incoming.get("newPasswordConfirm")

    if not check_password(current_password, member.password_hash):
        return JsonResponse({"ok": False, "error": "현재 비밀번호가 올바르지 않습니다."}, status=400)

    if new_password_confirm is not None and new_password != new_password_confirm:
        return JsonResponse({"ok": False, "error": "새 비밀번호가 일치하지 않습니다."}, status=400)

    password_error = _password_policy_error(new_password)
    if password_error:
        return JsonResponse({"ok": False, "error": password_error}, status=400)

    member.password_hash = make_password(new_password)
    member.save(update_fields=["password_hash"])

    return JsonResponse(
        {"ok": True, "message": "비밀번호가 변경되었습니다."},
        json_dumps_params={"ensure_ascii": False},
    )


@csrf_exempt
@require_POST
def stock_auth_update_profile(request):
    member = _session_member(request)
    if not member:
        return JsonResponse({"ok": False, "error": "로그인이 필요합니다."}, status=401)

    try:
        incoming = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    name = (incoming.get("name") or "").strip()
    if not name:
        return JsonResponse({"ok": False, "error": "성명을 입력해 주세요."}, status=400)

    member.name = name
    member.phone = (incoming.get("phone") or "").strip()
    if "postalCode" in incoming:
        member.postal_code = (incoming.get("postalCode") or "").strip()
    if "roadAddress" in incoming:
        member.road_address = (incoming.get("roadAddress") or "").strip()
    if "addressDetail" in incoming:
        member.address_detail = (incoming.get("addressDetail") or "").strip()
    member.save(
        update_fields=["name", "phone", "postal_code", "road_address", "address_detail", "updated_at"]
    )

    return JsonResponse({"ok": True, "member": member.to_public_dict()}, json_dumps_params={"ensure_ascii": False})


# --- 관리자: 회원 대상 메일 발송 (Django admin의 StockMemberAdmin 액션에서 연결) ---


@staff_sso_required(app="stock")
def stock_admin_member_email(request):
    """선택된 회원들에게 보낼 메일 제목/본문을 입력받는 중간 페이지.

    기존 exam_bulk_edit과 같은 패턴(관리자 액션 -> 중간 입력 페이지 ->
    처리 후 목록으로 리다이렉트)을 그대로 따른다.
    """
    ids = [value for value in (request.GET.get("ids") or request.POST.get("ids") or "").split(",") if value]
    members = list(StockMember.objects.filter(pk__in=ids))

    if not members:
        messages.error(request, "선택된 회원이 없습니다.")
        return redirect("admin:stock_stockmember_changelist")

    if request.method == "POST":
        subject = (request.POST.get("subject") or "").strip()
        message_body = request.POST.get("message") or ""

        if not message_body.strip():
            messages.error(request, "메일 내용을 입력해 주세요.")
        else:
            sent, failed = 0, 0
            for member in members:
                status, _note = _send_member_email(member.email, subject, message_body)
                if status == "sent":
                    sent += 1
                else:
                    failed += 1
            if failed:
                messages.warning(request, f"{sent}명 발송 성공, {failed}명 발송 실패했습니다.")
            else:
                messages.success(request, f"{sent}명에게 메일을 발송했습니다.")
            return redirect("admin:stock_stockmember_changelist")

    return render(
        request,
        "admin/stock/member_email.html",
        {"members": members, "ids": ",".join(ids)},
    )
