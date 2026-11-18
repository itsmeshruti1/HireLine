from datetime import timedelta
import hashlib
import json
from io import BytesIO

from docx import Document as WordDocument
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.config import Settings
from backend.app.db import now
from backend.app.main import create_app
from backend.app.models import Application, Assessment, AuditEvent, BackgroundJob, Candidate, IntegrationState, Job, OutboundAction, Screening, User
from backend.app.worker import enqueue, process_one


@pytest.fixture
def workspace(tmp_path):
    settings = Settings(app_env="test", database_url="sqlite:///"+str(tmp_path / "app.db"), checkpoint_url="sqlite:///"+str(tmp_path / "checkpoints.db"), local_storage_dir=str(tmp_path / "files"), worker_enabled=False, seed_demo=False, auth_mode="local", ai_mode="demo", external_mode="preview", app_secret="test-key-at-least-thirty-two-characters")
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            session.add_all([User(id="admin", email="admin@demo.local", name="Admin", role="admin"), User(id="recruiter", email="recruiter@demo.local", name="Recruiter", role="recruiter"), User(id="manager", email="manager@demo.local", name="Manager", role="manager")])
            session.add_all([Job(id="j1", title="Python engineer", description="Build reliable Python services", criteria=[{"id": "python", "label": "Python", "weight": 100}], criteria_confirmed=True, manager_ids=["manager"]), Job(id="j2", title="Other team", description="A different team's role", criteria=[{"id": "react", "label": "React", "weight": 100}], criteria_confirmed=True)])
            session.add_all([Candidate(id="c1", name="Synthetic One", email="one@example.test", skills=["Python"], segments=[{"id": "page-1", "text": "Synthetic One\nBuilt Python APIs and PostgreSQL applications."}]), Candidate(id="c2", name="Synthetic Two", email="two@example.test", segments=[{"id": "page-1", "text": "Built React interfaces."}])])
            session.commit()
            session.add_all([Application(id="a1", job_id="j1", candidate_id="c1"), Application(id="a2", job_id="j2", candidate_id="c2")])
            session.commit()
        yield client, app, settings


def headers(client, role="recruiter"):
    result = client.post("/api/auth/login", json={"email": role+"@demo.local", "password": "local-demo-only"})
    assert result.status_code == 200, result.text
    return {"Authorization": "Bearer "+result.json()["access_token"]}


def process(app, settings):
    assert process_one(app.state.session_factory, settings)


QUESTIONS = [{"id": "q1", "kind": "mcq", "prompt": "Which status means created?", "options": ["201", "404"], "answer": "201"}, {"id": "q2", "kind": "short", "prompt": "How would you handle API retries?", "rubric": "Discuss idempotency and bounded retries."}]


def test_login_preserves_password_whitespace():
    from backend.app.schemas import Login
    credentials = Login(email=" admin@example.test ", password=" passphrase ")
    assert credentials.email == "admin@example.test"
    assert credentials.password == " passphrase "


@pytest.mark.parametrize("options", [["201", "201"], ["201", " "], ["201", "x" * 2001]])
def test_ambiguous_or_unbounded_mcq_options_are_rejected(workspace, options):
    client, _, _ = workspace
    response = client.post("/api/applications/a1/assessment", headers=headers(client), json={"questions": [{**QUESTIONS[0], "options": options}]})
    assert response.status_code == 422


def test_calendar_query_cannot_exceed_seven_days(workspace):
    client, _, _ = workspace
    start = now() + timedelta(days=1)
    response = client.get("/api/integrations/calendar/freebusy", headers=headers(client), params={"start": start.isoformat(), "end": (start + timedelta(days=7, seconds=1)).isoformat()})
    assert response.status_code == 422


def test_duplicate_interview_returns_its_original_task(workspace):
    client, _, _ = workspace
    auth = headers(client)
    start = now() + timedelta(days=1)
    first_slot = {"start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat(), "timezone": "UTC"}
    second_slot = {"start": (start + timedelta(days=1)).isoformat(), "end": (start + timedelta(days=1, minutes=30)).isoformat(), "timezone": "UTC"}
    first = client.post("/api/applications/a1/interviews", headers=auth, json=first_slot)
    second = client.post("/api/applications/a1/interviews", headers=auth, json=second_slot)
    duplicate = client.post("/api/applications/a1/interviews", headers=auth, json=first_slot)
    assert first.status_code == second.status_code == duplicate.status_code == 202
    assert duplicate.json()["job_id"] == first.json()["job_id"]
    assert duplicate.json()["job_id"] != second.json()["job_id"]


def test_concurrent_reviews_enqueue_once(workspace):
    from concurrent.futures import ThreadPoolExecutor
    client, app, settings = workspace
    auth = headers(client)
    screening = client.post("/api/applications/a1/screen", headers=auth).json()
    process(app, settings)
    def review(_):
        return client.post(f"/api/screenings/{screening['screening_id']}/review", headers=auth, json={"approved": True, "notes": "Verified source"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(review, range(2)))
    assert sorted(result.status_code for result in results) == [202, 409]
    with app.state.session_factory() as session:
        assert len(list(session.scalars(select(BackgroundJob).where(BackgroundJob.kind == "screen_review")))) == 1


@pytest.mark.parametrize("change", ["token", "expiry"])
def test_invitation_changed_during_submission_cannot_be_used(workspace, monkeypatch, change):
    from sqlalchemy import update
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.dml import Update
    client, app, _ = workspace
    invited = client.post("/api/applications/a1/assessment", headers=headers(client), json={"questions": QUESTIONS}).json()
    token = invited["invite_url"].split("/")[-1]
    original_execute = Session.execute
    changed = False

    def execute(session, statement, *args, **kwargs):
        nonlocal changed
        if not changed and isinstance(statement, Update) and statement.table.name == "assessments":
            changed = True
            values = {"token_hash": "replacement-token"} if change == "token" else {"expires_at": now() - timedelta(seconds=1)}
            with app.state.engine.begin() as connection:
                connection.execute(update(Assessment).where(Assessment.id == invited["assessment"]["id"]).values(**values))
        return original_execute(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", execute)
    result = client.post("/api/invitations/" + token, json={"answers": {"q1": "201", "q2": "Use bounded retries"}})
    assert changed and result.status_code == 409
    with app.state.session_factory() as session:
        assessment = session.get(Assessment, invited["assessment"]["id"])
        assert assessment.status == "invited" and not assessment.answers
        assert not session.scalar(select(BackgroundJob).where(BackgroundJob.kind == "assessment_feedback"))


def test_concurrent_admin_demotions_retain_one_admin(workspace):
    from concurrent.futures import ThreadPoolExecutor
    client, app, _ = workspace
    auth = headers(client, "admin")
    assert client.patch("/api/staff/recruiter", headers=auth, json={"role": "admin"}).status_code == 200
    def demote(identifier):
        return client.patch(f"/api/staff/{identifier}", headers=auth, json={"role": "manager"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(demote, ["admin", "recruiter"]))
    assert sum(response.status_code == 200 for response in results) == 1
    assert all(response.status_code in {200, 403, 409} for response in results)
    with app.state.session_factory() as session:
        assert len(list(session.scalars(select(User).where(User.role == "admin")))) == 1


def test_full_workflow_persists_review_then_assessment_and_interview(workspace):
    client, app, settings = workspace
    auth = headers(client)
    start = client.post("/api/applications/a1/screen", headers=auth)
    assert start.status_code == 202
    screening_id = start.json()["screening_id"]
    process(app, settings)
    snap = client.get("/api/workspace", headers=auth).json()
    screening = next(s for s in snap["screenings"] if s["id"] == screening_id)
    assert screening["status"] == "awaiting_review" and screening["score"] == 100
    assert next(a for a in snap["applications"] if a["id"] == "a1")["stage"] == "new"
    restarted = create_app(settings)
    with TestClient(restarted) as second_client:
        response = second_client.post(f"/api/screenings/{screening_id}/review", headers=auth, json={"approved": True, "notes": "Verified resume evidence"})
        assert response.status_code == 202, response.text
        process(restarted, settings)
        assert second_client.patch("/api/applications/a1/stage", headers=auth, json={"stage": "shortlisted"}).status_code == 200
        invited = second_client.post("/api/applications/a1/assessment", headers=auth, json={"questions": QUESTIONS})
        assert invited.status_code == 201, invited.text
        token = invited.json()["invite_url"].split("/")[-1]
        candidate_view = second_client.get("/api/invitations/"+token).json()
        assert "answer" not in candidate_view["questions"][0]
        future = now()+timedelta(days=2)
        body = {"answers": {"q1": "201", "q2": "Use idempotency keys and exponential backoff."}, "availability": [{"start": future.isoformat(), "end": (future+timedelta(hours=1)).isoformat(), "timezone": "UTC"}]}
        assert second_client.post("/api/invitations/"+token, json=body).status_code == 200
        assert second_client.post("/api/invitations/"+token, json=body).status_code == 409
        process(restarted, settings)
        assessment_id = invited.json()["assessment"]["id"]
        review = second_client.post(f"/api/assessments/{assessment_id}/review", headers=auth, json={"notes": "Reviewed advisory feedback against rubric"})
        assert review.status_code == 200
        scheduled = second_client.post("/api/applications/a1/interviews", headers=auth, json={"start": future.isoformat(), "end": (future+timedelta(minutes=30)).isoformat(), "timezone": "UTC"})
        assert scheduled.status_code == 202, scheduled.text
        duplicate = second_client.post("/api/applications/a1/interviews", headers=auth, json={"start": future.isoformat(), "end": (future+timedelta(minutes=30)).isoformat(), "timezone": "UTC"})
        assert duplicate.json()["cached"]
        process(restarted, settings)
        assert second_client.post("/api/applications/a1/feedback", headers=auth, json={"rating": 4, "notes": "Clear examples and verified skills"}).status_code == 201
        assert second_client.patch("/api/applications/a1/stage", headers=auth, json={"stage": "hired", "note": "Recruiter confirmed the hiring outcome"}).status_code == 200
        final = second_client.get("/api/workspace", headers=auth).json()
        assert final["assessments"][0]["mcq_score"] == 100
        assert final["assessments"][0]["short_answer_feedback"][0]["requires_review"]
        assert final["interviews"][0]["status"] == "preview"
        assert final["screenings"][0]["status"] == "approved"


def test_manager_is_scoped_and_cannot_change_hiring_data(workspace):
    client, app, settings = workspace
    manager = headers(client, "manager")
    snap = client.get("/api/workspace", headers=manager).json()
    assert [j["id"] for j in snap["jobs"]] == ["j1"]
    assert [c["id"] for c in snap["candidates"]] == ["c1"]
    assert client.post("/api/applications/a1/feedback", headers=manager, json={"rating": 4, "notes": "Strong documented examples"}).status_code == 201
    assert client.post("/api/applications/a2/feedback", headers=manager, json={"rating": 4, "notes": "Should not be visible"}).status_code == 403
    assert client.patch("/api/applications/a1/stage", headers=manager, json={"stage": "hired", "note": "No permission"}).status_code == 403
    assert client.post("/api/applications/a1/screen", headers=manager).status_code == 403
    assert client.get("/api/staff", headers=manager).status_code == 403
    assert client.get("/api/workspace").status_code == 401


def test_public_demo_is_fixture_only_and_excludes_private_records(workspace):
    client, app, settings = workspace
    demo = client.get("/api/demo")
    assert demo.status_code == 200
    assert len(demo.json()["candidates"]) == 20
    assert "one@example.test" not in demo.text
    assert "token_hash" not in demo.text and "access_token" not in demo.text
    assert "email" not in demo.json()["candidates"][0]
    assert demo.headers["referrer-policy"] == "no-referrer"


def test_stale_review_rejected_after_profile_or_criteria_change(workspace):
    client, app, settings = workspace
    auth = headers(client)
    response = client.post("/api/applications/a1/screen", headers=auth)
    process(app, settings)
    id = response.json()["screening_id"]
    updated = client.patch("/api/candidates/c1", headers=auth, json={"headline": "Corrected extracted headline"})
    assert updated.json()["profile_version"] == 2
    assert client.post(f"/api/screenings/{id}/review", headers=auth, json={"approved": True}).status_code == 409
    response = client.post("/api/applications/a1/screen", headers=auth)
    process(app, settings)
    update = client.patch("/api/jobs/j1", headers=auth, json={"criteria": [{"id": "python", "label": "Python APIs", "weight": 100}], "criteria_confirmed": True})
    assert update.json()["criteria_version"] == 2
    assert client.post(f"/api/screenings/{response.json()['screening_id']}/review", headers=auth, json={"approved": True}).status_code == 409


def test_duplicate_screen_request_and_outbox_do_not_duplicate(workspace):
    client, app, settings = workspace
    auth = headers(client)
    first = client.post("/api/applications/a1/screen", headers=auth).json()
    second = client.post("/api/applications/a1/screen", headers=auth).json()
    assert first["job_id"] == second["job_id"]
    process(app, settings)
    invited = client.post("/api/applications/a1/assessment", headers=auth, json={"questions": QUESTIONS, "send_email": True})
    token = invited.json()["invite_url"].split("/")[-1]
    assert client.post("/api/applications/a1/assessment", headers=auth, json={"questions": QUESTIONS, "send_email": True}).status_code == 409
    with app.state.session_factory() as session:
        action = session.scalar(select(OutboundAction))
        assert token not in json.dumps(action.payload)
        assessment = session.scalar(select(Assessment))
        assert assessment.token_hash == hashlib.sha256(token.encode()).hexdigest()
    process(app, settings)
    snapshot = client.get("/api/workspace", headers=auth)
    assert token not in snapshot.text
    with app.state.session_factory() as session:
        action = session.scalar(select(OutboundAction))
        assert action.payload == {} and "body" not in action.result
        task = enqueue(session, "email", {"action_id": action.id}, "a1")
        session.commit()
    process(app, settings)
    with app.state.session_factory() as session:
        assert session.get(BackgroundJob, task.id).result["cached"]


def test_expired_invalid_incomplete_invitation_and_answer_key_secrecy(workspace):
    client, app, settings = workspace
    auth = headers(client)
    response = client.post("/api/applications/a1/assessment", headers=auth, json={"questions": QUESTIONS})
    token = response.json()["invite_url"].split("/")[-1]
    assert client.get("/api/invitations/not-a-token").status_code == 404
    assert client.post("/api/invitations/"+token, json={"answers": {"q1": "201"}}).status_code == 422
    snapshot = client.get("/api/workspace", headers=auth).json()
    assert all("answer" not in q for q in snapshot["assessments"][0]["questions"])
    with app.state.session_factory() as session:
        assessment = session.scalar(select(Assessment))
        assessment.expires_at = now()-timedelta(seconds=1)
        session.commit()
    assert client.get("/api/invitations/"+token).status_code == 410


def test_invalid_upload_and_synthetic_confirmation(workspace):
    client, app, settings = workspace
    auth = headers(client)
    assert client.post("/api/jobs/j1/uploads", headers=auth, files={"files": ("test.pdf", b"%PDF bad")}).status_code == 422
    assert client.post("/api/jobs/j1/uploads", headers=auth, data={"synthetic_confirmed": "true"}, files={"files": ("test.pdf", b"not a pdf")}).status_code == 422
    assert client.post("/api/jobs/j1/uploads", headers=auth, data={"synthetic_confirmed": "true"}, files={"files": ("test.exe", b"MZ")}).status_code == 422
    assert client.post("/api/candidates", headers=auth, json={"name": "Fake person"}).status_code == 422


def test_docx_import_and_duplicate_file_cached(workspace):
    client, app, settings = workspace
    auth = headers(client)
    doc = WordDocument()
    doc.add_paragraph("Synthetic Three")
    doc.add_paragraph("Built Python APIs with PostgreSQL and Docker for 3 years.")
    output = BytesIO()
    doc.save(output)
    content = output.getvalue()
    response = client.post("/api/jobs/j1/uploads", headers=auth, data={"synthetic_confirmed": "true"}, files={"files": ("three.docx", content)})
    assert response.status_code == 202, response.text
    process(app, settings)
    repeated = client.post("/api/jobs/j1/uploads", headers=auth, data={"synthetic_confirmed": "true"}, files={"files": ("three.docx", content)})
    assert repeated.json()["candidate_ids"] == response.json()["candidate_ids"]
    assert repeated.json()["job_ids"] == []
    task = client.get("/api/background-jobs/"+response.json()["job_ids"][0], headers=auth).json()
    assert task["status"] == "completed" and "_profile" not in task["result"]


def test_closed_decision_requires_note_and_last_admin_is_retained(workspace):
    client, app, settings = workspace
    auth = headers(client)
    assert client.patch("/api/applications/a1/stage", headers=auth, json={"stage": "hired"}).status_code == 422
    assert client.patch("/api/applications/a1/stage", headers=auth, json={"stage": "rejected", "note": "Recruiter reviewed evidence"}).status_code == 200
    assert client.patch("/api/applications/a1/stage", headers=auth, json={"stage": "new"}).status_code == 409
    admin = headers(client, "admin")
    assert client.patch("/api/staff/admin", headers=admin, json={"role": "manager"}).status_code == 409
    assert client.patch("/api/staff/manager", headers=admin, json={"role": "recruiter"}).status_code == 200


def test_recovery_reclaims_expired_lease_and_reset_rejects_active_work(workspace):
    client, app, settings = workspace
    auth = headers(client)
    response = client.post("/api/applications/a1/screen", headers=auth)
    with app.state.session_factory() as session:
        task = session.get(BackgroundJob, response.json()["job_id"])
        task.status, task.lease_until = "running", now()-timedelta(seconds=1)
        session.commit()
    assert client.post("/api/demo/reset", headers=headers(client, "admin")).status_code == 409
    process(app, settings)
    with app.state.session_factory() as session:
        assert session.get(BackgroundJob, response.json()["job_id"]).status == "completed"


def test_production_rejects_unsafe_configuration():
    with pytest.raises(ValueError, match="Supabase authentication"):
        Settings(app_env="production", auth_mode="local")
    with pytest.raises(ValueError, match="PostgreSQL workflow checkpoints"):
        Settings(app_env="production", auth_mode="supabase", database_url="postgresql+psycopg://user:pass@localhost/test", supabase_url="https://example.supabase.co", supabase_anon_key="configured", supabase_service_role_key="configured", app_secret="strong-production-secret-over-thirty-two-characters")


def test_conversion_counts_historical_stage_reached_not_current_distribution(workspace):
    client, app, settings = workspace
    auth = headers(client)
    assert client.patch("/api/applications/a1/stage", headers=auth, json={"stage": "shortlisted"}).status_code == 200
    assert client.patch("/api/applications/a1/stage", headers=auth, json={"stage": "rejected", "note": "Recorded outcome after review"}).status_code == 200
    metrics = client.get("/api/workspace", headers=auth).json()["metrics"]
    assert metrics["stage_counts"]["shortlisted"] == 0
    assert metrics["conversion_rates"]["new"] == 100
    assert metrics["conversion_rates"]["shortlisted"] == 50
    assert metrics["conversion_rates"]["rejected"] == 50
    assert metrics["conversion_rates"]["assessment"] == 0


def test_conversion_history_survives_activity_feed_limit(workspace):
    client, app, settings = workspace
    auth = headers(client)
    client.patch("/api/applications/a1/stage", headers=auth, json={"stage": "shortlisted"})
    client.patch("/api/applications/a1/stage", headers=auth, json={"stage": "rejected", "note": "Recorded outcome"})
    with app.state.session_factory() as session:
        session.add_all([AuditEvent(actor_id="recruiter", action="candidate.corrected", entity_id="c1", details={"edit": index}) for index in range(205)])
        session.commit()
    snapshot = client.get("/api/workspace", headers=auth).json()
    assert len(snapshot["activities"]) == 200
    assert not any(event["action"] == "application.stage_changed" for event in snapshot["activities"])
    assert snapshot["metrics"]["conversion_rates"]["shortlisted"] == 50


def test_profile_edit_during_model_call_cannot_overwrite_stale_status(workspace, monkeypatch):
    client, app, settings = workspace
    auth = headers(client)
    response = client.post("/api/applications/a1/screen", headers=auth)
    def model_call(*args, **kwargs):
        with app.state.session_factory() as session:
            session.get(Candidate, "c1").profile_version += 1
            session.commit()
        return {"matches": [], "score": 100, "missing_count": 0, "awaiting_review": True}
    monkeypatch.setattr("backend.app.services.screening.run_screening", model_call)
    process(app, settings)
    with app.state.session_factory() as session:
        assert session.get(Screening, response.json()["screening_id"]).status == "stale"
        assert session.get(BackgroundJob, response.json()["job_id"]).status == "failed"


def test_reinvite_recovers_expired_link_and_invalidates_previous_token(workspace):
    client, app, settings = workspace
    auth = headers(client)
    original = client.post("/api/applications/a1/assessment", headers=auth, json={"questions": QUESTIONS}).json()
    assessment_id = original["assessment"]["id"]
    old_token = original["invite_url"].split("/")[-1]
    with app.state.session_factory() as session:
        session.get(Assessment, assessment_id).expires_at = now()-timedelta(seconds=1)
        session.commit()
    assert client.get("/api/invitations/"+old_token).status_code == 410
    assert client.post(f"/api/assessments/{assessment_id}/reinvite", headers=headers(client, "manager"), json={}).status_code == 403
    renewed = client.post(f"/api/assessments/{assessment_id}/reinvite", headers=auth, json={})
    assert renewed.status_code == 200, renewed.text
    new_token = renewed.json()["invite_url"].split("/")[-1]
    assert new_token != old_token
    assert client.get("/api/invitations/"+old_token).status_code == 404
    assert client.get("/api/invitations/"+new_token).status_code == 200
    assert client.post("/api/invitations/"+new_token, json={"answers": {"q1": "201", "q2": "Use bounded retries and idempotency keys."}}).status_code == 200
    assert client.post(f"/api/assessments/{assessment_id}/reinvite", headers=auth, json={}).status_code == 409


def test_known_email_quota_failure_can_be_explicitly_retried_once(workspace, monkeypatch):
    from backend.app.services.errors import ServiceError
    client, app, settings = workspace
    auth = headers(client)
    sent_ids = []
    def send(self, action_id, to, subject, body):
        sent_ids.append(action_id)
        if len(sent_ids) == 1:
            raise ServiceError("429: email quota exhausted", retryable=True)
        return {"id": "provider-receipt", "status": "sent"}
    monkeypatch.setattr("backend.app.services.integrations.Integrations.send_email", send)
    assert client.post("/api/applications/a1/assessment", headers=auth, json={"questions": QUESTIONS, "send_email": True}).status_code == 201
    process(app, settings)
    with app.state.session_factory() as session:
        task = session.scalar(select(BackgroundJob).where(BackgroundJob.kind == "email"))
        action = session.get(OutboundAction, task.payload["action_id"])
        assert task.status == "failed" and action.status == "failed"
        assert action.payload.get("encrypted")
        task_id = task.id
    assert not process_one(app.state.session_factory, settings)
    assert client.post(f"/api/background-jobs/{task_id}/retry", headers=auth).status_code == 202
    process(app, settings)
    assert sent_ids[0] == sent_ids[1]
    with app.state.session_factory() as session:
        assert session.get(BackgroundJob, task_id).status == "completed"
        action = session.scalar(select(OutboundAction))
        assert action.status == "sent" and action.payload == {}
    assert client.post(f"/api/background-jobs/{task_id}/retry", headers=auth).status_code == 409
    assert not process_one(app.state.session_factory, settings)
    assert len(sent_ids) == 2


@pytest.mark.parametrize("unknown_error", [False, True])
def test_uncertain_email_delivery_cannot_be_retried(workspace, monkeypatch, unknown_error):
    from backend.app.services.errors import ServiceError
    client, app, settings = workspace
    auth = headers(client)
    def send(*args, **kwargs):
        if unknown_error:
            raise TimeoutError("Unknown outcome after dispatch")
        raise ServiceError("Provider connection timed out after dispatch", ambiguous=True)
    monkeypatch.setattr("backend.app.services.integrations.Integrations.send_email", send)
    client.post("/api/applications/a1/assessment", headers=auth, json={"questions": QUESTIONS, "send_email": True})
    process(app, settings)
    with app.state.session_factory() as session:
        task = session.scalar(select(BackgroundJob).where(BackgroundJob.kind == "email"))
        assert session.get(OutboundAction, task.payload["action_id"]).status == "needs_reconciliation"
        task_id = task.id
    assert client.post(f"/api/background-jobs/{task_id}/retry", headers=auth).status_code == 409
    assert not process_one(app.state.session_factory, settings)


def test_force_rescreens_approved_result_but_pending_work_always_deduplicates(workspace):
    client, app, settings = workspace
    auth = headers(client)
    first = client.post("/api/applications/a1/screen", headers=auth).json()
    process(app, settings)
    client.post(f"/api/screenings/{first['screening_id']}/review", headers=auth, json={"approved": True})
    process(app, settings)
    cached = client.post("/api/applications/a1/screen", headers=auth).json()
    assert cached["cached"] and cached["screening_id"] == first["screening_id"]
    forced = client.post("/api/applications/a1/screen", headers=auth, json={"force": True}).json()
    assert forced["screening_id"] != first["screening_id"]
    duplicate = client.post("/api/applications/a1/screen", headers=auth, json={"force": True}).json()
    assert duplicate["screening_id"] == forced["screening_id"]
    assert duplicate["engine"] == "demo" and duplicate["model"] is None


def test_seed_results_are_labelled_demo_and_never_reused_for_live_screening(workspace):
    client, app, settings = workspace
    auth = headers(client)
    with app.state.session_factory() as session:
        session.add(Screening(id="seed-score", application_id="a1", thread_id="seed-a1", criteria_version=1, profile_version=1, status="approved", score=100))
        session.commit()
    settings.ai_mode, settings.gemini_model = "gemini", "configured-free-model"
    response = client.post("/api/applications/a1/screen", headers=auth).json()
    assert response["screening_id"] != "seed-score" and response["engine"] == "gemini"
    assert response["model"] == "configured-free-model"
    results = client.get("/api/workspace", headers=auth).json()["screenings"]
    sample = next(result for result in results if result["id"] == "seed-score")
    assert sample["engine"] == "demo" and sample["model"] is None
    queued = next(result for result in results if result["id"] == response["screening_id"])
    assert queued["engine"] == "gemini" and queued["model"] == "configured-free-model"


@pytest.mark.parametrize("origin_engine,origin_model", [("demo", None), ("gemini", "previous-model")])
def test_provider_or_model_change_invalidates_approved_cache(workspace, origin_engine, origin_model):
    client, app, settings = workspace
    auth = headers(client)
    with app.state.session_factory() as session:
        session.add(Screening(id="prior-score", application_id="a1", thread_id="prior-workflow", criteria_version=1, profile_version=1, status="approved", score=100))
        session.add(BackgroundJob(kind="screen", application_id="a1", status="completed", payload={"screening_id": "prior-score", "ai_mode": origin_engine, "model": origin_model}))
        session.commit()
    settings.ai_mode, settings.gemini_model = "gemini", "new-model"
    response = client.post("/api/applications/a1/screen", headers=auth).json()
    assert response["screening_id"] != "prior-score"
    assert response["engine"] == "gemini" and response["model"] == "new-model"


def test_database_prevents_two_assessments_for_one_application(workspace):
    client, app, settings = workspace
    with app.state.session_factory() as session:
        first = Assessment(application_id="a1", token_hash="a"*64, expires_at=now()+timedelta(days=7))
        session.add(first)
        session.commit()
        session.add(Assessment(application_id="a1", token_hash="b"*64, expires_at=now()+timedelta(days=7)))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert len(list(session.scalars(select(Assessment).where(Assessment.application_id == "a1")))) == 1


def store_fake_calendar(app, settings):
    from backend.app.auth import encryption
    tokens = {"access_token": "fake-old-access", "refresh_token": "fake-stable-refresh", "connected_at": now().isoformat(), "expires_at": (now()+timedelta(hours=1)).isoformat()}
    with app.state.session_factory() as session:
        session.add(IntegrationState(provider="google_calendar", status="connected", encrypted_tokens=encryption(settings).encrypt(json.dumps(tokens).encode()).decode(), expires_at=now()+timedelta(hours=1)))
        session.commit()
    return tokens


@pytest.mark.parametrize("permanent_error", [None, False, True])
def test_calendar_rotated_tokens_persist_and_only_permanent_failure_disconnects(workspace, monkeypatch, permanent_error):
    from backend.app.auth import encryption
    from backend.app.services.errors import ServiceError
    client, app, settings = workspace
    settings.external_mode = "live"
    original = store_fake_calendar(app, settings)
    def freebusy(self, tokens, start, end):
        tokens.update({"access_token": "fake-rotated-access", "expires_at": (now()+timedelta(hours=2)).isoformat()})
        if permanent_error is not None:
            raise ServiceError("Mock Calendar temporarily unavailable" if not permanent_error else "Mock Calendar authorization revoked", retryable=not permanent_error, reconnect_required=permanent_error)
        return {"busy": []}
    monkeypatch.setattr("backend.app.services.integrations.Integrations.freebusy", freebusy)
    future = now()+timedelta(days=1)
    response = client.get("/api/integrations/calendar/freebusy", headers=headers(client), params={"start": future.isoformat(), "end": (future+timedelta(hours=1)).isoformat()})
    assert response.status_code == (200 if permanent_error is None else 409)
    with app.state.session_factory() as session:
        state = session.scalar(select(IntegrationState).where(IntegrationState.provider == "google_calendar"))
        tokens = json.loads(encryption(settings).decrypt(state.encrypted_tokens.encode()).decode())
        assert tokens["access_token"] == "fake-rotated-access"
        assert tokens["refresh_token"] == original["refresh_token"]
        assert tokens["connected_at"] == original["connected_at"]
        assert state.status == ("reconnect_required" if permanent_error else "connected")


def test_interview_worker_persists_rotated_calendar_tokens(workspace, monkeypatch):
    from backend.app.auth import encryption
    client, app, settings = workspace
    settings.external_mode, settings.calendar_allowed_emails = "live", "owned@example.test"
    store_fake_calendar(app, settings)
    def create_event(self, action_id, tokens, start, end, attendees, **kwargs):
        tokens.update({"access_token": "fake-after-event-refresh", "expires_at": (now()+timedelta(hours=2)).isoformat()})
        return {"id": "mock-event", "status": "sent"}
    monkeypatch.setattr("backend.app.services.integrations.Integrations.create_event", create_event)
    future = now()+timedelta(days=1)
    response = client.post("/api/applications/a1/interviews", headers=headers(client), json={"start": future.isoformat(), "end": (future+timedelta(minutes=30)).isoformat(), "timezone": "UTC"})
    assert response.status_code == 202
    process(app, settings)
    with app.state.session_factory() as session:
        state = session.scalar(select(IntegrationState).where(IntegrationState.provider == "google_calendar"))
        tokens = json.loads(encryption(settings).decrypt(state.encrypted_tokens.encode()).decode())
        assert tokens["access_token"] == "fake-after-event-refresh"
