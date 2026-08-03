"""AIStockQuote 회원 계정.

AURA(apps/aura_app/models.py의 AuraMember)와 동일한 패턴을 그대로 따른다: 이메일을
로그인 아이디로 쓰고, 비밀번호는 Django의 make_password/check_password로 해시
저장하며, 회원가입/비밀번호 재설정은 DB에 저장된 1회용 고엔트로피 토큰
(secrets.token_urlsafe(32))으로 처리한다.

다만 이 사이트는 국내 회원 위주라서 주소를 자유 형식 JSON이 아니라 다음(카카오)
우편번호 서비스 결과에 맞춘 3개 필드(postal_code/road_address/address_detail)로
구조화해서 저장한다.
"""
import uuid

from django.db import models


def _new_member_id():
    return f"member-{uuid.uuid4().hex[:12]}"


class StockMember(models.Model):
    id = models.CharField(max_length=40, primary_key=True, default=_new_member_id, editable=False)

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=80)  # 성명(실명)

    password_hash = models.CharField(max_length=255)

    phone = models.CharField(max_length=40, blank=True)
    is_phone_verified = models.BooleanField(default=False)

    # 다음(카카오) 우편번호 서비스 팝업 결과를 그대로 저장한다.
    # postal_code: 5자리 우편번호, road_address: 도로명(또는 지번) 주소,
    # address_detail: 팝업이 못 채워주는 동/호수 등 사용자가 직접 입력하는 상세주소.
    postal_code = models.CharField(max_length=10, blank=True)
    road_address = models.CharField(max_length=200, blank=True)
    address_detail = models.CharField(max_length=200, blank=True)

    is_email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    email_verification_expires_at = models.DateTimeField(null=True, blank=True)

    password_reset_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    password_reset_expires_at = models.DateTimeField(null=True, blank=True)

    # 주소/연락처 등 개인정보를 수집하므로(개인정보보호법 제15조) 가입 시점에
    # 수집·이용 동의 여부와 시각을 감사 목적으로 남겨둔다.
    privacy_consent_accepted = models.BooleanField(default=False)
    privacy_consent_accepted_at = models.DateTimeField(null=True, blank=True)

    # 소셜 로그인(카카오/네이버/구글/애플). apps/aura_app/models.py의 AuraMember와
    # 동일한 이유로 social_provider/social_uid는 null=True(빈 문자열이 아니라)로
    # 둔다 -- unique_together(social_provider, social_uid)에서 NULL은 서로 다른
    # 값으로 취급되므로, 이메일/비밀번호로만 가입한 회원이 전부 NULL이어도 제약이
    # 깨지지 않는다.
    SOCIAL_PROVIDER_CHOICES = [
        ("kakao", "카카오"),
        ("naver", "네이버"),
        ("google", "구글"),
        ("apple", "애플"),
    ]
    social_provider = models.CharField(
        max_length=20, choices=SOCIAL_PROVIDER_CHOICES, null=True, blank=True
    )
    social_uid = models.CharField(max_length=191, null=True, blank=True)
    social_email = models.EmailField(blank=True)
    social_linked_at = models.DateTimeField(null=True, blank=True)

    role = models.CharField(max_length=20, default="member")
    memo = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("social_provider", "social_uid")]

    def __str__(self):
        return f"{self.name} <{self.email}>"

    @property
    def full_address(self):
        if not self.road_address:
            return ""
        parts = [f"[{self.postal_code}]" if self.postal_code else "", self.road_address, self.address_detail]
        return " ".join(part for part in parts if part).strip()

    def to_public_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "isEmailVerified": self.is_email_verified,
            "isPhoneVerified": self.is_phone_verified,
            "phone": self.phone,
            "postalCode": self.postal_code,
            "roadAddress": self.road_address,
            "addressDetail": self.address_detail,
            "role": self.role,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
            "socialProvider": self.social_provider,
        }


class LoginHistory(models.Model):
    """로그인 시도 이력(성공/실패 모두 기록).

    개인정보보호법 시행령 제30조상 접속기록 보관 요건 대응(apps/aura_app/models.py의
    LoginHistory와 동일한 패턴 — 회원 테이블이 앱별로 분리돼 있으므로 이력 테이블도
    앱별로 각각 둔다).
    """

    member = models.ForeignKey(
        StockMember,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="login_history",
    )
    attempted_email = models.EmailField()
    success = models.BooleanField()
    failure_reason = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "로그인 기록"
        verbose_name_plural = "로그인 기록"

    def __str__(self):
        status = "성공" if self.success else "실패"
        return f"[{status}] {self.attempted_email} ({self.created_at:%Y-%m-%d %H:%M})"


class WatchlistItem(models.Model):
    member = models.ForeignKey(StockMember, on_delete=models.CASCADE, related_name="watchlist")
    symbol = models.CharField(max_length=30)
    display_name = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = [("member", "symbol")]


class RecentlyViewedStock(models.Model):
    member = models.ForeignKey(StockMember, on_delete=models.CASCADE, related_name="recent_stocks")
    symbol = models.CharField(max_length=30)
    viewed_at = models.DateTimeField(auto_now=True)
    class Meta:
        unique_together = [("member", "symbol")]
        ordering = ["-viewed_at"]


class PriceAlert(models.Model):
    CONDITION_CHOICES = [("above", "가격 이상"), ("below", "가격 이하"), ("change_up", "등락률 이상"), ("change_down", "등락률 이하")]
    member = models.ForeignKey(StockMember, on_delete=models.CASCADE, related_name="price_alerts")
    symbol = models.CharField(max_length=30)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES)
    threshold = models.DecimalField(max_digits=18, decimal_places=4)
    is_active = models.BooleanField(default=True)
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MarketEvent(models.Model):
    EVENT_CHOICES = [("earnings", "실적 발표"), ("dividend", "배당"), ("meeting", "주주총회")]
    symbol = models.CharField(max_length=30, db_index=True)
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES)
    title = models.CharField(max_length=200)
    event_at = models.DateTimeField()
    source_name = models.CharField(max_length=120)
    source_url = models.URLField()
    is_estimated = models.BooleanField(default=False)


class StockNewsItem(models.Model):
    symbol = models.CharField(max_length=30, db_index=True)
    title = models.CharField(max_length=240)
    source_name = models.CharField(max_length=120)
    source_url = models.URLField()
    published_at = models.DateTimeField()
    fact_summary = models.TextField()
    market_interpretation = models.TextField(blank=True)


class DataQualityLog(models.Model):
    symbol = models.CharField(max_length=30, blank=True)
    provider = models.CharField(max_length=80, default="Yahoo Finance via yfinance")
    status = models.CharField(max_length=20, default="success")
    is_delayed = models.BooleanField(default=True)
    reference_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ConsentItem(models.Model):
    """회원가입 동의 항목 1건 (2026-07-22 신설 -- apps/aura_app.models.ConsentItem과
    동일한 구조/역할). 이전에는 StockMember.privacy_consent_accepted 하나만 있었는데,
    그 값은 이제 이 중 "privacy-policy"(개인정보처리방침) 항목에 흡수됐다.
    """

    key = models.SlugField(max_length=60, unique=True)
    label = models.CharField(max_length=120)
    is_required = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    enacted_at = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "key"]

    def __str__(self):
        return self.label

    @property
    def active_revision(self):
        return self.revisions.filter(is_active=True).order_by("-version").first()


class ConsentItemRevision(models.Model):
    item = models.ForeignKey(ConsentItem, related_name="revisions", on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    title_ko = models.CharField(max_length=200)
    title_en = models.CharField(max_length=200)
    body_ko = models.TextField()
    body_en = models.TextField()
    change_summary = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["item", "-version"]
        unique_together = [("item", "version")]

    def __str__(self):
        return f"{self.item.label} v{self.version}"

    def to_public_dict(self):
        return {
            "key": self.item.key,
            "label": self.item.label,
            "isRequired": self.item.is_required,
            "version": self.version,
            "titleKo": self.title_ko,
            "titleEn": self.title_en,
            "bodyKo": self.body_ko,
            "bodyEn": self.body_en,
            "enactedAt": self.item.enacted_at.isoformat(),
            "changedAt": self.changed_at.isoformat(),
            "changeSummary": self.change_summary,
            "isActive": self.is_active,
            "publishUrl": f"/stock/terms/{self.item.key}/",
        }


class MemberConsentAgreement(models.Model):
    member_id = models.CharField(max_length=40, db_index=True)
    item_key = models.SlugField(max_length=60)
    version = models.PositiveIntegerField()
    agreed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-agreed_at"]

    def __str__(self):
        return f"{self.member_id} agreed {self.item_key} v{self.version}"

    def to_public_dict(self):
        return {
            "itemKey": self.item_key,
            "version": self.version,
            "agreedAt": self.agreed_at.isoformat(),
        }
