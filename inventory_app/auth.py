from __future__ import annotations

from functools import wraps

from flask import abort, current_app, request
from flask_login import current_user


ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER)


def login_disabled() -> bool:
    return bool(current_app.config.get("LOGIN_DISABLED"))


def role_required(*roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if login_disabled():
                return view(*args, **kwargs)
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def admin_required(view):
    return role_required(ROLE_ADMIN)(view)


def write_required(view):
    return role_required(ROLE_ADMIN, ROLE_OPERATOR)(view)


def require_login_for_main_routes():
    if login_disabled():
        return None
    if request.endpoint and request.endpoint.startswith("main.") and not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    return None


def role_label(role: str) -> str:
    return {
        ROLE_ADMIN: "管理员",
        ROLE_OPERATOR: "录入员",
        ROLE_VIEWER: "查看员",
    }.get(role, role)
