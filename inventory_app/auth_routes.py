from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from .auth import ROLE_ADMIN, ROLES, admin_required, role_label
from .extensions import db
from .models import User


bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            login_user(user)
            return redirect(request.args.get("next") or url_for("main.dashboard"))
        flash("用户名或密码错误，或账号已停用。", "danger")

    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("已退出登录。", "success")
    return redirect(url_for("auth.login"))


@bp.route("/users", methods=["GET", "POST"])
@login_required
@admin_required
def users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", ROLE_ADMIN)
        is_active = request.form.get("is_active") == "on"
        try:
            if not username:
                raise ValueError("用户名不能为空。")
            if role not in ROLES:
                raise ValueError("角色无效。")
            if not password:
                raise ValueError("新建用户必须填写密码。")
            db.session.add(
                User(
                    username=username,
                    password_hash=generate_password_hash(password),
                    role=role,
                    is_active=is_active,
                )
            )
            db.session.commit()
            flash("用户已创建。", "success")
            return redirect(url_for("auth.users"))
        except IntegrityError:
            db.session.rollback()
            flash("用户名已存在。", "danger")
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    user_list = User.query.order_by(User.created_at.desc(), User.id.desc()).all()
    return render_template("users.html", users=user_list, roles=ROLES, role_label=role_label)


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(user_id: int):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("不能停用当前登录账号。", "warning")
        return redirect(url_for("auth.users"))
    user.is_active = not user.is_active
    db.session.commit()
    flash("用户状态已更新。", "success")
    return redirect(url_for("auth.users"))


@bp.route("/users/<int:user_id>/password", methods=["POST"])
@login_required
@admin_required
def reset_user_password(user_id: int):
    user = db.get_or_404(User, user_id)
    password = request.form.get("password", "")
    if not password:
        flash("新密码不能为空。", "danger")
        return redirect(url_for("auth.users"))
    user.set_password(password)
    db.session.commit()
    flash("密码已重置。", "success")
    return redirect(url_for("auth.users"))
