"""회원가입 동의 항목(ConsentItem) 조회·개정·설정 관리 로직 (2026-07-22 신설).

apps/aura_app/domain/services/consent_service.py와 동일한 패턴/기본값을 그대로
포팅했다 (기준은 aura). StockMember.privacy_consent_accepted(개인정보 수집·이용
동의) 단일 필드는 이 중 "privacy-policy" 항목으로 흡수됐다.
"""
from __future__ import annotations

from django.utils import timezone
from django.utils.text import slugify

from apps.stock.models import ConsentItem, ConsentItemRevision

DEFAULT_ITEMS = [
    {"key": "terms-of-service", "label": "이용약관 동의", "is_required": True, "sort_order": 10},
    {"key": "privacy-policy", "label": "개인정보처리방침 동의", "is_required": True, "sort_order": 20},
    {"key": "ai-service-guide", "label": "AI 서비스 이용안내", "is_required": True, "sort_order": 30},
    {"key": "marketing-consent", "label": "마케팅 수신동의", "is_required": False, "sort_order": 40},
    {"key": "location-terms", "label": "위치정보이용약관", "is_required": False, "sort_order": 50},
]


def ensure_default_items() -> None:
    for default in DEFAULT_ITEMS:
        ConsentItem.objects.get_or_create(
            key=default["key"],
            defaults={
                "label": default["label"],
                "is_required": default["is_required"],
                "is_published": False,
                "sort_order": default["sort_order"],
                "enacted_at": timezone.now().date(),
            },
        )


def list_items():
    ensure_default_items()
    return ConsentItem.objects.all().order_by("sort_order", "key")


def admin_payload() -> list:
    items = []
    for item in list_items():
        revisions = item.revisions.order_by("-version")
        items.append(
            {
                "key": item.key,
                "label": item.label,
                "isRequired": item.is_required,
                "isPublished": item.is_published,
                "sortOrder": item.sort_order,
                "enactedAt": item.enacted_at.isoformat(),
                "publishUrl": f"/stock/terms/{item.key}/",
                "active": item.active_revision.to_public_dict() if item.active_revision else None,
                "history": [revision.to_public_dict() for revision in revisions],
            }
        )
    return items


def public_active_payload() -> list:
    result = []
    for item in list_items():
        if not item.is_published:
            continue
        revision = item.active_revision
        if not revision:
            continue
        result.append(revision.to_public_dict())
    return result


def get_public_item(key: str):
    item = ConsentItem.objects.filter(key=key).first()
    if not item or not item.is_published:
        return None
    revision = item.active_revision
    if not revision:
        return None
    return revision.to_public_dict()


def create_item(*, label: str, key: str = "", is_required: bool = True, sort_order: int = 0):
    label = (label or "").strip()
    if not label:
        return 400, {"ok": False, "error": "항목 이름을 입력해 주세요."}

    key = slugify(key or label, allow_unicode=False)
    if not key:
        return 400, {"ok": False, "error": "항목 key를 만들 수 없습니다 (영문/숫자 라벨을 함께 입력해 주세요)."}

    if ConsentItem.objects.filter(key=key).exists():
        return 409, {"ok": False, "error": f"이미 존재하는 key입니다: {key}"}

    item = ConsentItem.objects.create(
        key=key, label=label, is_required=is_required, is_published=False,
        sort_order=sort_order, enacted_at=timezone.now().date(),
    )
    return 200, {"ok": True, "item": {
        "key": item.key, "label": item.label, "isRequired": item.is_required,
        "isPublished": item.is_published, "sortOrder": item.sort_order,
        "enactedAt": item.enacted_at.isoformat(), "publishUrl": f"/stock/terms/{item.key}/",
        "active": None, "history": [],
    }}


def update_item_settings(key: str, incoming: dict):
    item = ConsentItem.objects.filter(key=key).first()
    if not item:
        return 404, {"ok": False, "error": "항목을 찾을 수 없습니다."}

    if "label" in incoming:
        label = (incoming.get("label") or "").strip()
        if not label:
            return 400, {"ok": False, "error": "항목 이름은 비울 수 없습니다."}
        item.label = label
    if "isRequired" in incoming:
        item.is_required = bool(incoming.get("isRequired"))
    if "isPublished" in incoming:
        item.is_published = bool(incoming.get("isPublished"))
    if "sortOrder" in incoming:
        try:
            item.sort_order = int(incoming.get("sortOrder"))
        except (TypeError, ValueError):
            pass
    item.save()

    return 200, {"ok": True, "items": admin_payload()}


def save_revision(incoming: dict):
    key = (incoming.get("key") or "").strip()
    item = ConsentItem.objects.filter(key=key).first()
    if not item:
        return 404, {"ok": False, "error": "항목을 찾을 수 없습니다."}

    title_ko = (incoming.get("titleKo") or "").strip()
    title_en = (incoming.get("titleEn") or "").strip()
    body_ko = (incoming.get("bodyKo") or "").strip()
    body_en = (incoming.get("bodyEn") or "").strip()
    change_summary = (incoming.get("changeSummary") or "").strip()

    if not title_ko or not title_en or not body_ko or not body_en:
        return 400, {"ok": False, "error": "제목/본문(한/영)을 모두 입력해 주세요."}

    is_first_version = not item.revisions.exists()
    if not is_first_version and not change_summary:
        return 400, {"ok": False, "error": "변경내용을 입력해 주세요(최초 제정이 아닌 개정입니다)."}

    last_version = item.revisions.order_by("-version").values_list("version", flat=True).first() or 0
    item.revisions.filter(is_active=True).update(is_active=False)
    revision = ConsentItemRevision.objects.create(
        item=item, version=last_version + 1, title_ko=title_ko, title_en=title_en,
        body_ko=body_ko, body_en=body_en, change_summary=change_summary or "최초 제정",
        is_active=True, changed_by=(incoming.get("changedBy") or "").strip(),
    )

    return 200, {"ok": True, "revision": revision.to_public_dict(), "items": admin_payload()}
