import re
from django.conf import settings
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("", lambda request: redirect("/stock/")),
    path("admin/", admin.site.urls),
    path("stock/", include("apps.stock.urls")),
    re_path(r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")), serve, {"document_root": settings.MEDIA_ROOT}),
]
