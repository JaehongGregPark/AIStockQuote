"""Standalone Stock administration authorization helpers."""
from functools import wraps
from urllib.parse import quote
from django.http import JsonResponse
from django.shortcuts import redirect

def current_staff_label(request):
    user = getattr(request, "user", None)
    return user.get_username() if user and user.is_authenticated else ""

def has_access(request, app=None):
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_staff)

def staff_sso_required(app=None):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if has_access(request, app):
                return view_func(request, *args, **kwargs)
            return redirect(f"/admin/login/?next={quote(request.get_full_path())}")
        return wrapper
    return decorator

def staff_sso_required_json(view_func=None, *, app=None):
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not has_access(request, app):
                return JsonResponse({"detail": "관리자 로그인이 필요합니다."}, status=403)
            return func(request, *args, **kwargs)
        return wrapper
    return decorator(view_func) if view_func is not None else decorator
