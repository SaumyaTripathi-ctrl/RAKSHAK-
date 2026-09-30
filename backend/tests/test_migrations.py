"""The Alembic migrations must produce exactly the schema the ORM models describe."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[1]


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_head_matches_models_and_downgrades(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'mig.db'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if models and migrations differ (autogenerate would emit changes)
    command.downgrade(cfg, "base")
