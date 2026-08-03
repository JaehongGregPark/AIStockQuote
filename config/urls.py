import re
from django.conf import settings
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path, re_path
from django.views.static import serve
from django.views.generic import RedirectView

urlpatterns = [
    path("", lambda request: redirect("/stock/")),
    # IntegratedHub에서 사용하던 AppSetting 관리자 URL을 독립 앱의
    # API key 관리 화면으로 연결한다. 현재 프로젝트에는 lexicon 앱이 없다.
    path(
        "admin/lexicon/appsetting/",
        RedirectView.as_view(url="/stock/stock-admin/?tab=api", permanent=False),
        name="legacy_appsetting_admin",
    ),
    path("admin/", admin.site.urls),
    path("stock/", include("apps.stock.urls")),
    re_path(r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")), serve, {"document_root": settings.MEDIA_ROOT}),
]
