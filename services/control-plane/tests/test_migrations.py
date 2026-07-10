from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_round_trip_and_model_drift(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.db"
    config = Config("services/control-plane/alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")

    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(f"sqlite:///{database_path}")
    tables = set(inspect(engine).get_table_names())
    assert {
        "api_credentials",
        "deletion_requests",
        "deletion_tasks",
        "phrase_artifacts",
        "practice_sessions",
        "score_records",
        "song_manifest_records",
        "songs",
        "stored_assets",
        "tenants",
    } <= tables
    engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{database_path}")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()
