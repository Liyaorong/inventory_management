from __future__ import annotations

import os
from datetime import date

import click
from flask import Flask

from .auth import role_label
from .extensions import db, login_manager, migrate
from .utils import format_decimal


def _sqlite_uri(path: str) -> str:
    normalized = os.path.abspath(path).replace("\\", "/")
    return f"sqlite:///{normalized}"


def _ensure_sqlite_parent(uri: str):
    if not uri.startswith("sqlite:///") or uri.endswith(":memory:"):
        return
    db_path = uri.replace("sqlite:///", "", 1)
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    default_db_path = os.path.join(app.instance_path, "inventory.db")
    env_database_url = os.environ.get("DATABASE_URL")
    if env_database_url and env_database_url.startswith("postgres://"):
        env_database_url = env_database_url.replace("postgres://", "postgresql+psycopg://", 1)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-key"),
        SQLALCHEMY_DATABASE_URI=env_database_url or _sqlite_uri(default_db_path),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        AUTO_CREATE_DB=os.environ.get("AUTO_CREATE_DB", "1") == "1",
    )

    if test_config:
        app.config.update(test_config)
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if uri.startswith("sqlite:///") and "\\\\" not in uri:
            app.config["SQLALCHEMY_DATABASE_URI"] = uri.replace("\\", "/")

    os.makedirs(app.instance_path, exist_ok=True)
    _ensure_sqlite_parent(app.config["SQLALCHEMY_DATABASE_URI"])

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from . import models
    from .auth import ROLE_ADMIN, ROLE_OPERATOR, require_login_for_main_routes
    from .auth_routes import bp as auth_bp
    from .routes import bp

    @login_manager.user_loader
    def load_user(user_id: str):
        if not user_id.isdigit():
            return None
        return db.session.get(models.User, int(user_id))

    app.register_blueprint(auth_bp)
    app.register_blueprint(bp)
    app.before_request(require_login_for_main_routes)
    app.jinja_env.filters["decimal"] = format_decimal
    app.jinja_env.globals["today"] = date.today

    @app.context_processor
    def inject_auth_helpers():
        return {
            "ROLE_ADMIN": ROLE_ADMIN,
            "ROLE_OPERATOR": ROLE_OPERATOR,
            "role_label": role_label,
        }

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(username: str, password: str):
        if models.User.query.filter_by(username=username).first():
            raise click.ClickException("User already exists.")
        user = models.User(username=username, role=ROLE_ADMIN, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created admin user: {username}")

    if app.config.get("AUTO_CREATE_DB"):
        with app.app_context():
            db.create_all()

    return app
