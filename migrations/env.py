from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config
fileConfig(config.config_file_name)

target_db = current_app.extensions["migrate"].db
target_metadata = target_db.metadata


def get_engine():
    return target_db.engine


def get_engine_url():
    return str(get_engine().url).replace("%", "%%")


def run_migrations_offline():
    context.configure(
        url=get_engine_url(),
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    conf_args = current_app.extensions["migrate"].configure_args
    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            **conf_args,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
