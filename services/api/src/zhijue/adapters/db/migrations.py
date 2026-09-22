"""Programmatic Alembic entry used before the API opens its business database."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

API_ROOT = Path(__file__).resolve().parents[4]


def upgrade_database(database_url: str) -> None:
    """Bring the selected business database to the repository migration head.

    The migration chain owns persistent schema changes.  In particular, this
    must run before repositories open the database so an old ``create_all``
    schema cannot accept traffic while silently missing later columns.
    """
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
