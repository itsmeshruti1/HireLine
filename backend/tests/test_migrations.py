import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect
from sqlalchemy import MetaData, UniqueConstraint, select, text
from sqlalchemy.orm import Session
import pytest

from backend.app.db import Base, now
from backend.app.migrations import prepare_database
from backend.app.models import Application, Assessment, Candidate, Job
from datetime import timedelta


def test_fresh_schema_upgrade_is_repeatable_and_reversible(tmp_path):
    root = Path(__file__).resolve().parents[2]
    url = "sqlite:///" + (tmp_path / "migrated.db").as_posix()
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "test", "AUTH_MODE": "local"}
    command = [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini"]
    for _ in range(2):
        subprocess.run([*command, "upgrade", "head"], cwd=root, env=env, check=True, capture_output=True, text=True)
    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {"jobs", "candidates", "applications", "screenings", "assessments", "background_jobs",
            "outbound_actions", "staff_users", "integration_states"} <= tables
    engine.dispose()
    subprocess.run([*command, "downgrade", "base"], cwd=root, env=env, check=True, capture_output=True, text=True)
    engine = create_engine(url)
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


def legacy_database(tmp_path, duplicate_assessments=False):
    engine = create_engine("sqlite:///"+(tmp_path / "legacy.db").as_posix())
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    for constraint in list(metadata.tables["assessments"].constraints):
        if isinstance(constraint, UniqueConstraint) and tuple(column.name for column in constraint.columns) == ("application_id",):
            metadata.tables["assessments"].constraints.remove(constraint)
    metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Job(id="retained-job", title="Retained synthetic role", description="Existing user-created job"))
        session.add(Candidate(id="retained-candidate", name="Retained Synthetic Candidate"))
        session.commit()
        session.add(Application(id="retained-application", job_id="retained-job", candidate_id="retained-candidate"))
        session.commit()
        session.add(Assessment(id="retained-assessment", application_id="retained-application", token_hash="a"*64, expires_at=now()+timedelta(days=7)))
        if duplicate_assessments:
            session.add(Assessment(id="duplicate-assessment", application_id="retained-application", token_hash="b"*64, expires_at=now()+timedelta(days=7)))
        session.commit()
    return engine


@pytest.mark.parametrize("empty_version_table", [False, True])
def test_startup_adopts_complete_legacy_schema_without_losing_records(tmp_path, empty_version_table):
    engine = legacy_database(tmp_path)
    if empty_version_table:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
    prepare_database(engine, "local")
    prepare_database(engine, "local")
    with Session(engine) as session:
        assert session.get(Job, "retained-job").title == "Retained synthetic role"
        assert session.get(Assessment, "retained-assessment").application_id == "retained-application"
        assert session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    uniques = inspect(engine).get_indexes("assessments")
    assert any(index["unique"] and index["column_names"] == ["application_id"] for index in uniques)
    engine.dispose()


def test_legacy_duplicates_block_migration_without_deleting_records(tmp_path):
    engine = legacy_database(tmp_path, duplicate_assessments=True)
    with pytest.raises(RuntimeError, match="duplicate applications"):
        prepare_database(engine, "local")
    with Session(engine) as session:
        assert len(list(session.scalars(select(Assessment)))) == 2
    assert "alembic_version" not in inspect(engine).get_table_names()
    engine.dispose()


def test_partial_or_unversioned_production_schema_is_not_silently_adopted(tmp_path):
    engine = create_engine("sqlite:///"+(tmp_path / "partial.db").as_posix())
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE jobs (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO jobs (id) VALUES ('keep-this-record')"))
    with pytest.raises(RuntimeError, match="incomplete schema"):
        prepare_database(engine, "local")
    with pytest.raises(RuntimeError, match="unversioned business tables"):
        prepare_database(engine, "production")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM jobs")).scalar_one() == "keep-this-record"
    engine.dispose()
