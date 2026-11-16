"""Exercise the production database/checkpointer in CI; opt in locally with POSTGRES_TEST_URL."""
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

URL = os.getenv("POSTGRES_TEST_URL", "")
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not URL, reason="POSTGRES_TEST_URL is not configured")
def test_postgres_migration_and_durable_review():
    from app.db import make_database
    from app.models import Job
    from app.services.screening import run_screening
    from sqlalchemy import select

    environment = {**os.environ, "DATABASE_URL": URL, "APP_ENV": "test", "AUTH_MODE": "local"}
    subprocess.run([sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
                   cwd=ROOT, env=environment, check=True, capture_output=True, text=True)
    engine, session_factory = make_database(URL)
    identifier = "ci-" + uuid4().hex
    with session_factory() as session:
        session.add(Job(id=identifier, title="CI test", description="Synthetic role", criteria=[], manager_ids=[]))
        session.commit()
    with session_factory() as session:
        assert session.scalar(select(Job).where(Job.id == identifier)).title == "CI test"
        session.delete(session.get(Job, identifier))
        session.commit()
    engine.dispose()
    checkpoint_url = URL.replace("postgresql+psycopg://", "postgresql://", 1)
    segments = [{"id": "page-1", "text": "Synthetic candidate built Python APIs."}]
    criteria = [{"id": "python", "label": "Python", "weight": 100}]
    paused = run_screening(identifier, segments, criteria, checkpoint_url)
    assert paused["awaiting_review"] is True
    # Constructing a new graph/checkpointer represents a new API process after restart.
    resumed = run_screening(identifier, segments, criteria, checkpoint_url,
                           resume={"approved": True, "notes": "CI reviewer confirmed source"})
    assert resumed["approved"] is True
    assert resumed["awaiting_review"] is False


@pytest.mark.skipif(not URL, reason="POSTGRES_TEST_URL is not configured")
def test_postgres_queue_skips_locked_job():
    from backend.app.db import make_database, now
    from backend.app.models import BackgroundJob
    from backend.app.worker import claim_job
    from sqlalchemy import delete, select
    engine, factory = make_database(URL)
    identifiers = ["pg-queue-"+uuid4().hex, "pg-queue-"+uuid4().hex]
    try:
        with factory() as session:
            session.add_all([BackgroundJob(id=identifiers[0], kind="test", created_at=now()-timedelta(minutes=2)), BackgroundJob(id=identifiers[1], kind="test", created_at=now()-timedelta(minutes=1))])
            session.commit()
        with factory() as locked, factory() as other:
            locked.scalar(select(BackgroundJob).where(BackgroundJob.id == identifiers[0]).with_for_update())
            assert claim_job(other) == identifiers[1]
            locked.rollback()
        with factory() as session:
            assert claim_job(session) == identifiers[0]
    finally:
        with factory() as session:
            session.execute(delete(BackgroundJob).where(BackgroundJob.id.in_(identifiers)))
            session.commit()
        engine.dispose()


@pytest.mark.skipif(not URL, reason="POSTGRES_TEST_URL is not configured")
def test_postgres_concurrent_screen_and_assessment_are_idempotent():
    from fastapi.testclient import TestClient
    from backend.app.config import Settings
    from backend.app.main import create_app
    from backend.app.models import Application, Assessment, AuditEvent, BackgroundJob, Candidate, Job, OutboundAction, Screening, User
    from sqlalchemy import delete, select
    marker = "pg-api-"+uuid4().hex
    ids = {kind: marker+"-"+kind for kind in ["staff", "job", "candidate", "application"]}
    settings = Settings(_env_file=None, app_env="test", auth_mode="local", database_url=URL, checkpoint_url=URL.replace("postgresql+psycopg://", "postgresql://"), ai_mode="demo", external_mode="preview", seed_demo=False, worker_enabled=False, app_secret="isolated-postgres-api-test-never-production")
    app = create_app(settings)
    try:
        with TestClient(app) as client:
            with app.state.session_factory() as session:
                session.add(User(id=ids["staff"], email=marker+"@example.test", name="Postgres Test Recruiter", role="recruiter"))
                session.add(Job(id=ids["job"], title="Postgres test role", description="Synthetic Python role", criteria=[{"id": "python", "label": "Python", "weight": 100}], criteria_confirmed=True))
                session.add(Candidate(id=ids["candidate"], name="Postgres Synthetic Candidate", email="synthetic@example.test", segments=[{"id": "page-1", "text": "Built Python APIs."}]))
                session.commit()
                session.add(Application(id=ids["application"], job_id=ids["job"], candidate_id=ids["candidate"]))
                session.commit()
            login = client.post("/api/auth/login", json={"email": marker+"@example.test", "password": "local-demo-only"})
            assert login.status_code == 200
            headers = {"Authorization": "Bearer "+login.json()["access_token"]}
            def screen(_):
                return client.post(f"/api/applications/{ids['application']}/screen", headers=headers)
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(screen, range(2)))
            assert all(response.status_code == 202 for response in responses)
            assert len({response.json()["screening_id"] for response in responses}) == 1
            snapshot = client.get("/api/workspace", headers=headers).json()
            screening = next(item for item in snapshot["screenings"] if item["application_id"] == ids["application"])
            assert screening["engine"] == "demo" and screening["model"] is None
            def assess(_):
                return client.post(f"/api/applications/{ids['application']}/assessment", headers=headers, json={"questions": [{"id": "q1", "kind": "mcq", "prompt": "Which code means created?", "options": ["201", "404"], "answer": "201"}], "send_email": True})
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(assess, range(2)))
            assert sorted(response.status_code for response in responses) == [201, 409]
            with app.state.session_factory() as session:
                assert len(list(session.scalars(select(Screening).where(Screening.application_id == ids["application"])))) == 1
                assert len(list(session.scalars(select(Assessment).where(Assessment.application_id == ids["application"])))) == 1
                assert len(list(session.scalars(select(OutboundAction).where(OutboundAction.application_id == ids["application"])))) == 1
    finally:
        with app.state.session_factory() as session:
            entity_ids = [ids["application"], *session.scalars(select(Screening.id).where(Screening.application_id == ids["application"])), *session.scalars(select(Assessment.id).where(Assessment.application_id == ids["application"]))]
            session.execute(delete(AuditEvent).where(AuditEvent.entity_id.in_(entity_ids)))
            for model in [BackgroundJob, OutboundAction, Assessment, Screening]:
                session.execute(delete(model).where(model.application_id == ids["application"]))
            session.execute(delete(Application).where(Application.id == ids["application"]))
            session.execute(delete(Candidate).where(Candidate.id == ids["candidate"]))
            session.execute(delete(Job).where(Job.id == ids["job"]))
            session.execute(delete(User).where(User.id == ids["staff"]))
            session.commit()
        app.state.engine.dispose()


@pytest.mark.skipif(not URL, reason="POSTGRES_TEST_URL is not configured")
def test_postgres_non_utc_session_preserves_timestamp_instants():
    from backend.app.db import as_utc, make_database, now
    from sqlalchemy import text
    engine, _ = make_database(URL)
    instant = now().replace(microsecond=0)
    try:
        with engine.begin() as connection:
            connection.execute(text("SET LOCAL TIME ZONE 'Asia/Kolkata'"))
            returned = connection.execute(text("SELECT CAST(:instant AS timestamptz)"), {"instant": instant}).scalar_one()
            assert returned.utcoffset().total_seconds() == 19800
            assert as_utc(returned) == instant
    finally:
        engine.dispose()
