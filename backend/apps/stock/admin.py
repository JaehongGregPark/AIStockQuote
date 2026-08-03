from datetime import timedelta

from django.contrib import admin
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone

from .models import DataQualityLog, LoginHistory, MarketEvent, PriceAlert, RecentlyViewedStock, StockMember, StockNewsItem, WatchlistItem

# apps/aura_app/admin.py의 LOGIN_HISTORY_INLINE_WINDOW_DAYS와 동일한 이유(슬라이싱한
# 쿼리셋은 InlineModelAdmin이 내부적으로 다시 filter()를 걸 때 에러가 난다)로 건수
# 대신 기간으로 제한한다.
LOGIN_HISTORY_INLINE_WINDOW_DAYS = 90


class LoginHistoryInline(admin.TabularInline):
    """회원 상세 화면에서 바로 접속기록을 볼 수 있도록 하는 읽기 전용 인라인."""

    model = LoginHistory
    fk_name = "member"
    verbose_name = "접속기록"
    verbose_name_plural = f"접속기록(최근 {LOGIN_HISTORY_INLINE_WINDOW_DAYS}일)"
    fields = ["success", "failure_reason", "ip_address", "user_agent", "created_at"]
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = False

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        cutoff = timezone.now() - timedelta(days=LOGIN_HISTORY_INLINE_WINDOW_DAYS)
        return super().get_queryset(request).filter(created_at__gte=cutoff).order_by("-created_at")


@admin.register(StockMember)
class StockMemberAdmin(admin.ModelAdmin):
    inlines = [LoginHistoryInline]
    list_display = ["email", "name", "phone", "is_email_verified", "is_phone_verified", "signup_path", "role", "created_at"]
    search_fields = ["email", "name", "phone", "road_address"]
    list_filter = ["is_email_verified", "is_phone_verified", "role", "social_provider"]
    readonly_fields = [
        "id",
        "password_hash",
        "email_verification_token",
        "email_verification_expires_at",
        "password_reset_token",
        "password_reset_expires_at",
        "social_uid",
        "social_email",
        "social_linked_at",
        "created_at",
        "updated_at",
    ]
    fieldsets = (
        (None, {"fields": ("id", "email", "name", "role", "memo")}),
        ("연락처/주소", {"fields": ("phone", "postal_code", "road_address", "address_detail")}),
        ("인증/보안", {
            "fields": (
                "password_hash",
                "is_email_verified",
                "is_phone_verified",
                "email_verification_token",
                "email_verification_expires_at",
                "password_reset_token",
                "password_reset_expires_at",
            ),
        }),
        ("소셜 로그인", {"fields": ("social_provider", "social_uid", "social_email", "social_linked_at")}),
        ("동의", {"fields": ("privacy_consent_accepted", "privacy_consent_accepted_at")}),
        ("기록", {"fields": ("created_at", "updated_at")}),
    )
    actions = [
        "action_send_verification_email",
        "action_send_password_reset_email",
        "action_send_custom_email",
        "action_unlink_social_account",
    ]
    change_list_template = "stock/admin/stockmember_change_list.html"


    @admin.display(description="가입경로")
    def signup_path(self, obj):
        if obj.social_provider:
            return obj.get_social_provider_display()
        return "이메일"

    @admin.action(description="선택 회원의 소셜 로그인 연동 해제(이메일/비밀번호 계정으로 전환)")
    def action_unlink_social_account(self, request, queryset):
        updated = queryset.exclude(social_provider__isnull=True).update(
            social_provider=None, social_uid=None, social_email="", social_linked_at=None
        )
        self.message_user(
            request,
            f"{updated}명의 소셜 연동을 해제했습니다. 비밀번호가 없던 계정은 "
            "'선택 회원에게 비밀번호 재설정 링크 발송' 액션으로 새 비밀번호를 설정해야 로그인할 수 있습니다.",
        )

    def changelist_view(self, request, extra_context=None):
        provider_counts = {
            row["social_provider"]: row["count"]
            for row in StockMember.objects.exclude(social_provider__isnull=True)
            .values("social_provider")
            .annotate(count=Count("id"))
        }
        email_only_count = StockMember.objects.filter(social_provider__isnull=True).count()
        stats = [{"label": "이메일", "count": email_only_count}] + [
            {"label": label, "count": provider_counts.get(code, 0)}
            for code, label in StockMember.SOCIAL_PROVIDER_CHOICES
        ]
        extra_context = extra_context or {}
        extra_context["signup_path_stats"] = stats
        return super().changelist_view(request, extra_context=extra_context)

    @admin.action(description="선택 회원에게 이메일 인증 메일 재발송")
    def action_send_verification_email(self, request, queryset):
        from .views import _generate_email_verification, _send_verification_email

        sent = 0
        for member in queryset:
            if member.is_email_verified:
                continue
            token = _generate_email_verification(member)
            status, _note = _send_verification_email(request, member, token)
            if status == "sent":
                sent += 1
        self.message_user(request, f"{sent}명에게 인증 메일을 재발송했습니다.")

    @admin.action(description="선택 회원에게 비밀번호 재설정 링크 발송")
    def action_send_password_reset_email(self, request, queryset):
        from .views import _generate_password_reset, _send_password_reset_email

        sent = 0
        for member in queryset:
            token = _generate_password_reset(member)
            status, _note = _send_password_reset_email(request, member, token)
            if status == "sent":
                sent += 1
        self.message_user(request, f"{sent}명에게 비밀번호 재설정 메일을 발송했습니다.")

    @admin.action(description="선택 회원에게 메일 보내기")
    def action_send_custom_email(self, request, queryset):
        ids = ",".join(str(pk) for pk in queryset.values_list("pk", flat=True))
        url = reverse("stock_admin_member_email")
        return HttpResponseRedirect(f"{url}?ids={ids}")


@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ["member", "symbol", "display_name", "created_at"]
    search_fields = ["member__email", "symbol", "display_name"]


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = ["member", "symbol", "condition", "threshold", "is_active", "last_triggered_at"]
    list_filter = ["condition", "is_active"]


@admin.register(RecentlyViewedStock)
class RecentlyViewedStockAdmin(admin.ModelAdmin):
    list_display = ["member", "symbol", "viewed_at"]


@admin.register(MarketEvent)
class MarketEventAdmin(admin.ModelAdmin):
    list_display = ["symbol", "event_type", "title", "event_at", "source_name", "is_estimated"]
    list_filter = ["event_type", "is_estimated"]
    search_fields = ["symbol", "title"]


@admin.register(StockNewsItem)
class StockNewsItemAdmin(admin.ModelAdmin):
    list_display = ["symbol", "title", "source_name", "published_at"]
    search_fields = ["symbol", "title", "fact_summary"]


@admin.register(DataQualityLog)
class DataQualityLogAdmin(admin.ModelAdmin):
    list_display = ["symbol", "provider", "status", "is_delayed", "reference_at", "created_at"]
    list_filter = ["status", "is_delayed", "provider"]
    readonly_fields = [field.name for field in DataQualityLog._meta.fields]


@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    """로그인 접속기록 조회 전용(감사 목적이라 읽기 전용으로 둔다)."""

    list_display = ["attempted_email", "success", "failure_reason", "ip_address", "created_at"]
    list_filter = ["success", "created_at"]
    search_fields = ["attempted_email", "ip_address"]
    readonly_fields = [field.name for field in LoginHistory._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
