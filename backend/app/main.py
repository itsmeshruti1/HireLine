from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import logging
import secrets
import threading
from urllib.parse import quote

import jwt
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from . import schemas
from .auth import admin, assert_job_access, current_user, encryption, login, recruiter
from .config import Settings, get_settings
from .db import as_utc, make_database, now, serialize, uid
from .migrations import prepare_database
from .models import Application, Assessment, AuditEvent, BackgroundJob, Candidate, Document, Feedback, IntegrationState, Interview, Job, OutboundAction, Screening, User
from .seed import seed_database
from .worker import calendar_tokens, enqueue, mark_calendar_error, persist_calendar_tokens, worker_loop


logger = logging.getLogger(__name__)
STAGES = ["new", "screening", "shortlisted", "assessment", "interview", "hired", "rejected", "withdrawn"]


def db_session(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def audit(session, user, action, entity_id, **details):
    session.add(AuditEvent(actor_id=user.id if user else "candidate", action=action, entity_id=entity_id, details=details))


def get_application(session, user, id, lock=False):
    if lock:
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        application = session.scalar(select(Application).where(Application.id == id).with_for_update())
    else:
        application = session.get(Application, id)
    if application is None:
        raise HTTPException(404, "Application not found")
    assert_job_access(user, session.get(Job, application.job_id))
    return application


def validate_criteria(criteria):
    if not criteria or len({c["id"] for c in criteria}) != len(criteria):
        raise HTTPException(422, "Provide criteria with unique IDs")
    if abs(sum(c["weight"] for c in criteria) - 100) > .01:
        raise HTTPException(422, "Criteria weights must add up to 100")


def validate_managers(session, ids):
    for id in ids:
        user = session.get(User, id)
        if user is None or user.role not in {"manager", "admin"}:
            raise HTTPException(422, "Each assigned manager must be an existing manager or admin")


def screening_engine(session, screening):
    if screening.thread_id.startswith("seed-"):
        return {"engine": "demo", "model": None}
    origin = session.scalar(select(BackgroundJob).where(BackgroundJob.kind == "screen", BackgroundJob.payload["screening_id"].as_string() == screening.id).order_by(BackgroundJob.created_at).limit(1))
    engine = origin.payload.get("ai_mode") if origin else None
    if engine not in {"demo", "gemini"}:
        return {"engine": "unknown", "model": None}
    return {"engine": engine, "model": origin.payload.get("model") if engine == "gemini" else None}


def metrics_for(applications, jobs, tasks, activities):
    stages = {stage: 0 for stage in STAGES}
    stages.update(Counter(a["stage"] for a in applications))
    total = len(applications)
    durations = {stage: [] for stage in STAGES}
    reached_counts = {stage: 0 for stage in STAGES}
    for application in applications:
        transitions = sorted((e for e in activities if e["entity_id"] == application["id"] and e["action"] == "application.stage_changed"), key=lambda e: e["created_at"])
        entered = datetime.fromisoformat(application["created_at"])
        stage = "new"
        reached = {"new", application["stage"]}
        for event in transitions:
            event_time = datetime.fromisoformat(event["created_at"])
            durations.setdefault(stage, []).append(max(0, (event_time-entered).total_seconds() / 86400))
            entered, stage = event_time, event["details"].get("to", stage)
            reached.update(value for value in (event["details"].get("from"), event["details"].get("to")) if value in STAGES)
        durations.setdefault(stage, []).append(max(0, (now()-entered).total_seconds() / 86400))
        for observed in reached:
            if observed in reached_counts:
                reached_counts[observed] += 1
    return {"total_candidates": len({a["candidate_id"] for a in applications}), "open_jobs": sum(j["status"] == "open" for j in jobs), "active_applications": sum(a["stage"] not in {"hired", "rejected", "withdrawn"} for a in applications), "hired": stages["hired"], "stage_counts": stages, "conversion_rates": {stage: round(count/total*100, 1) if total else 0 for stage, count in reached_counts.items()}, "stage_durations": {stage: round(sum(values)/len(values), 1) if values else 0 for stage, values in durations.items()}, "processing_failures": sum(t["status"] == "failed" for t in tasks)}


def snapshot(session, user):
    jobs = [serialize(j) for j in session.scalars(select(Job).order_by(Job.created_at.desc())) if user.role != "manager" or user.id in j.manager_ids]
    job_ids = {j["id"] for j in jobs}
    applications = [serialize(a) for a in session.scalars(select(Application).where(Application.job_id.in_(job_ids)).order_by(Application.created_at.desc()))]
    app_ids = {a["id"] for a in applications}
    candidate_ids = {a["candidate_id"] for a in applications}
    if user.role in {"admin", "recruiter"}:
        candidates = [serialize(c, ("segments",)) for c in session.scalars(select(Candidate).order_by(Candidate.created_at.desc()))]
    else:
        candidates = [serialize(c, ("segments",)) for c in session.scalars(select(Candidate).where(Candidate.id.in_(candidate_ids)))]
    for candidate in candidates:
        candidate["documents"] = [serialize(d, ("storage_key", "segments", "content_hash")) for d in session.scalars(select(Document).where(Document.candidate_id == candidate["id"]))]
    screenings = [{**serialize(s, ("thread_id",)), **screening_engine(session, s)} for s in session.scalars(select(Screening).where(Screening.application_id.in_(app_ids)).order_by(Screening.created_at.desc()))]
    assessments = [serialize(a, ("token_hash",)) for a in session.scalars(select(Assessment).where(Assessment.application_id.in_(app_ids)))]
    for assessment in assessments:
        assessment["questions"] = [{k: v for k, v in q.items() if k != "answer"} for q in assessment["questions"]]
    interviews = [serialize(i) for i in session.scalars(select(Interview).where(Interview.application_id.in_(app_ids)))]
    feedback = [serialize(f) for f in session.scalars(select(Feedback).where(Feedback.application_id.in_(app_ids)))]
    visible_entities = app_ids | job_ids | {c["id"] for c in candidates} | {s["id"] for s in screenings} | {a["id"] for a in assessments}
    activities = [serialize(e) for e in session.scalars(select(AuditEvent).where(AuditEvent.entity_id.in_(visible_entities)).order_by(AuditEvent.created_at.desc()).limit(200))]
    stage_history = [serialize(e) for e in session.scalars(select(AuditEvent).where(AuditEvent.entity_id.in_(app_ids), AuditEvent.action == "application.stage_changed"))]
    task_query = select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(100)
    tasks = [serialize(t, ("payload", "lease_until", "next_attempt_at")) for t in session.scalars(task_query) if user.role != "manager" or t.application_id in app_ids]
    actions = [serialize(a, ("payload", "dedupe_key")) for a in session.scalars(select(OutboundAction).where(OutboundAction.application_id.in_(app_ids)))]
    users = [serialize(u) for u in session.scalars(select(User))] if user.role != "manager" else [serialize(user)]
    return {"jobs": jobs, "candidates": candidates, "applications": applications, "screenings": screenings, "assessments": assessments, "interviews": interviews, "feedback": feedback, "activities": activities, "tasks": tasks, "actions": actions, "users": users, "metrics": metrics_for(applications, jobs, tasks, stage_history)}


def fixture_demo():
    """Public data never comes from mutable staff business records."""
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic.json"
    if not fixture.exists():
        return {"jobs": [], "candidates": [], "applications": [], "screenings": [], "assessments": [], "interviews": [], "feedback": [], "activities": [], "tasks": [], "users": [], "metrics": metrics_for([], [], [], [])}
    from .services.ai import evaluate
    data = json.loads(fixture.read_text(encoding="utf-8"))
    created = (now()-timedelta(days=10)).isoformat()
    jobs = [{**{k: v for k, v in j.items() if k != "employment_type"}, "status": "open", "criteria_version": 1, "criteria_confirmed": True, "manager_ids": [], "created_at": created} for j in data["jobs"]]
    candidates, applications, screenings = [], [], []
    for index, row in enumerate(data["candidates"]):
        candidates.append({k: v for k, v in row.items() if k in {"id", "name", "headline", "skills", "experience_years", "location", "notice_period_days", "salary_expectation", "profile_version"}} | {"created_at": created, "documents": []})
        application = {"id": f"application-{index+1:02}", "candidate_id": row["id"], "job_id": row["job_id"], "stage": row.get("stage", "new"), "created_at": created, "updated_at": created}
        applications.append(application)
        job = next(j for j in jobs if j["id"] == application["job_id"])
        matches = evaluate(row["segments"], job["criteria"], mode="demo")
        weights = {c["id"]: c["weight"] for c in job["criteria"]}
        for match in matches:
            match["weight"] = weights.get(match.get("criterion_id"), 0)
        score = sum(m["weight"] * {"supported": 1, "partial": .5}.get(m["status"], 0) for m in matches)
        screenings.append({"id": f"screening-{index+1:02}", "application_id": application["id"], "score": round(score, 1), "matches": matches, "criteria_version": 1, "profile_version": 1, "missing_count": sum(m["status"] == "insufficient" for m in matches), "status": "approved", "review_notes": "Synthetic sample result", "reviewed_at": created, "created_at": created, "engine": "demo", "model": None})
    return {"jobs": jobs, "candidates": candidates, "applications": applications, "screenings": screenings, "assessments": [], "interviews": [], "feedback": [], "activities": [], "tasks": [], "actions": [], "users": [], "metrics": metrics_for(applications, jobs, [], [])}


def create_app(settings: Settings | None = None):
    settings = settings or get_settings()
    engine, factory = make_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        prepare_database(engine, settings.app_env)
        if settings.seed_demo:
            with factory() as session:
                seed_database(session, settings)
        stop = threading.Event()
        worker = None
        if settings.worker_enabled:
            worker = threading.Thread(target=worker_loop, args=(factory, settings, stop), daemon=True, name="recruiter-worker")
            worker.start()
        app.state.public_demo = fixture_demo()
        yield
        stop.set()
        if worker:
            worker.join(timeout=3)
        engine.dispose()

    app = FastAPI(title="Recruiter AI Workspace", version="1.0.0", lifespan=lifespan)
    app.state.settings, app.state.session_factory, app.state.engine = settings, factory, engine
    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url.rstrip("/")], allow_credentials=False, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok", "ai_mode": settings.ai_mode, "external_mode": settings.external_mode}

    @app.get("/api/config")
    def config():
        return {"auth_mode": settings.auth_mode, "ai_mode": settings.ai_mode, "external_mode": settings.external_mode, "local_login": settings.auth_mode == "local", "frontend_url": settings.frontend_url, "worker_sleeps": settings.app_env == "production", "demo_reset_enabled": settings.app_env != "production" or settings.enable_demo_reset}

    @app.post("/api/auth/login")
    def sign_in(body: schemas.Login, session=Depends(db_session)):
        return login(settings, session, body.email, body.password)

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return serialize(user)

    @app.get("/api/demo")
    def demo(request: Request):
        return request.app.state.public_demo

    @app.get("/api/workspace")
    def workspace(user=Depends(current_user), session=Depends(db_session)):
        return snapshot(session, user)

    @app.get("/api/staff")
    def staff(user=Depends(admin), session=Depends(db_session)):
        return [serialize(u) for u in session.scalars(select(User))]

    @app.patch("/api/staff/{id}")
    def change_role(id: str, body: dict, user=Depends(admin), session=Depends(db_session)):
        if set(body) != {"role"} or body["role"] not in {"admin", "recruiter", "manager"}:
            raise HTTPException(422, "Provide a role: admin, recruiter, or manager")
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        staff_users = list(session.scalars(select(User).order_by(User.id).with_for_update()))
        staff_user = next((account for account in staff_users if account.id == id), None)
        if not staff_user:
            raise HTTPException(404, "Staff account not found")
        admins = [account for account in staff_users if account.role == "admin"]
        if staff_user.role == "admin" and body["role"] != "admin" and len(admins) == 1:
            raise HTTPException(409, "The workspace must retain at least one admin")
        previous = staff_user.role
        staff_user.role = body["role"]
        audit(session, user, "staff.role_changed", id, previous=previous, role=body["role"])
        session.commit()
        return serialize(staff_user)

    @app.post("/api/jobs/draft-criteria")
    def draft_criteria(body: schemas.DraftInput, user=Depends(recruiter)):
        from .services.ai import draft_criteria
        try:
            return {"criteria": draft_criteria(body.description, mode=settings.ai_mode)}
        except Exception as error:
            raise HTTPException(503, str(error)[:400])

    @app.post("/api/jobs", status_code=201)
    def create_job(body: schemas.JobInput, user=Depends(recruiter), session=Depends(db_session)):
        data = body.model_dump()
        if data["criteria"]:
            validate_criteria(data["criteria"])
        elif data["criteria_confirmed"]:
            raise HTTPException(422, "Add screening criteria before confirming")
        validate_managers(session, data["manager_ids"])
        job = Job(**data)
        session.add(job)
        session.flush()
        audit(session, user, "job.created", job.id)
        session.commit()
        return serialize(job)

    @app.patch("/api/jobs/{id}")
    def update_job(id: str, body: schemas.JobPatch, user=Depends(recruiter), session=Depends(db_session)):
        job = session.get(Job, id)
        assert_job_access(user, job)
        data = body.model_dump(exclude_unset=True)
        if any(v is None for v in data.values()):
            raise HTTPException(422, "Job fields cannot be null")
        if "manager_ids" in data:
            validate_managers(session, data["manager_ids"])
        if "criteria" in data:
            validate_criteria(data["criteria"])
            if data["criteria"] != job.criteria:
                job.criteria_version += 1
                job.criteria_confirmed = False
                for screening in session.scalars(select(Screening).join(Application, Application.id == Screening.application_id).where(Application.job_id == id)):
                    screening.status = "stale"
        if data.get("criteria_confirmed") and not data.get("criteria", job.criteria):
            raise HTTPException(422, "Add screening criteria before confirming")
        for key, value in data.items():
            setattr(job, key, value)
        audit(session, user, "job.updated", id, criteria_version=job.criteria_version)
        session.commit()
        return serialize(job)

    @app.post("/api/candidates", status_code=201)
    def create_candidate(body: schemas.CandidateInput, user=Depends(recruiter), session=Depends(db_session)):
        if not body.synthetic_confirmed:
            raise HTTPException(422, "Confirm that this candidate and resume are synthetic")
        data = body.model_dump(exclude={"resume_text", "synthetic_confirmed"})
        candidate = Candidate(**data, segments=[{"id": "manual-1", "text": body.resume_text}] if body.resume_text else [])
        session.add(candidate)
        session.flush()
        audit(session, user, "candidate.created", candidate.id, synthetic=True)
        session.commit()
        return serialize(candidate, ("segments",))

    @app.patch("/api/candidates/{id}")
    def update_candidate(id: str, body: schemas.CandidatePatch, user=Depends(recruiter), session=Depends(db_session)):
        candidate = session.get(Candidate, id)
        if not candidate:
            raise HTTPException(404, "Candidate not found")
        data = body.model_dump(exclude_unset=True)
        for key, value in data.items():
            if key == "resume_text":
                candidate.segments = [{"id": "corrected-1", "text": value or ""}]
            elif value is not None or key in {"experience_years", "notice_period_days"}:
                setattr(candidate, key, value)
        candidate.profile_version += 1
        for screening in session.scalars(select(Screening).join(Application, Application.id == Screening.application_id).where(Application.candidate_id == id)):
            screening.status = "stale"
        audit(session, user, "candidate.corrected", id, profile_version=candidate.profile_version)
        session.commit()
        return serialize(candidate, ("segments",))

    @app.post("/api/jobs/{id}/applications", status_code=201)
    def add_application(id: str, body: schemas.ApplicationInput, user=Depends(recruiter), session=Depends(db_session)):
        assert_job_access(user, session.get(Job, id))
        if not session.get(Candidate, body.candidate_id):
            raise HTTPException(404, "Candidate not found")
        existing = session.scalar(select(Application).where(Application.job_id == id, Application.candidate_id == body.candidate_id))
        if existing:
            return serialize(existing)
        application = Application(job_id=id, candidate_id=body.candidate_id)
        session.add(application)
        session.flush()
        audit(session, user, "application.created", application.id, stage="new")
        session.commit()
        return serialize(application)

    @app.post("/api/jobs/{id}/uploads", status_code=202)
    async def upload(id: str, files: list[UploadFile] = File(...), synthetic_confirmed: bool = Form(False), user=Depends(recruiter), session=Depends(db_session)):
        assert_job_access(user, session.get(Job, id))
        if not synthetic_confirmed:
            raise HTTPException(422, "Confirm that every uploaded resume is synthetic")
        if not 1 <= len(files) <= 10:
            raise HTTPException(422, "Upload one to ten resumes per batch")
        validated = []
        for file in files:
            filename = Path(file.filename or "").name
            suffix = Path(filename).suffix.lower()
            if suffix not in {".pdf", ".docx"}:
                raise HTTPException(422, "Only text-based PDF and DOCX files are supported")
            content = await file.read(5 * 1024 * 1024 + 1)
            if not content or len(content) > 5 * 1024 * 1024:
                raise HTTPException(422, "Each resume must be nonempty and at most 5 MB")
            if (suffix == ".pdf" and not content.startswith(b"%PDF")) or (suffix == ".docx" and not content.startswith(b"PK")):
                raise HTTPException(422, "The file contents do not match the resume format")
            validated.append((filename[:255], suffix, content))
        from .services.storage import DocumentStorage
        storage = DocumentStorage(settings)
        tasks, candidates, keys = [], [], []
        try:
            for filename, suffix, content in validated:
                digest = hashlib.sha256(content).hexdigest()
                existing_doc = session.scalar(select(Document).join(Application, Application.candidate_id == Document.candidate_id).where(Application.job_id == id, Document.content_hash == digest))
                if existing_doc:
                    candidates.append(existing_doc.candidate_id)
                    continue
                candidate = Candidate(name=Path(filename).stem.replace("_", " ")[:160])
                session.add(candidate)
                session.flush()
                key = f"{candidate.id}/{uid()}{suffix}"
                keys.append(key)
                await run_in_threadpool(storage.put, key, content, "application/pdf" if suffix == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                document = Document(candidate_id=candidate.id, filename=filename, storage_key=key, content_hash=digest)
                application = Application(job_id=id, candidate_id=candidate.id)
                session.add_all([document, application])
                session.flush()
                tasks.append(enqueue(session, "import", {"document_id": document.id}, application.id).id)
                candidates.append(candidate.id)
                audit(session, user, "application.created", application.id, stage="new", synthetic=True)
            session.commit()
        except Exception:
            session.rollback()
            for key in keys:
                try:
                    await run_in_threadpool(storage.delete, key)
                except Exception:
                    logger.warning("Storage cleanup needed for an interrupted upload")
            raise
        return {"job_ids": tasks, "candidate_ids": candidates}

    @app.get("/api/documents/{id}/download")
    def download(id: str, user=Depends(current_user), session=Depends(db_session)):
        document = session.get(Document, id)
        if not document:
            raise HTTPException(404, "Document not found")
        if user.role == "manager":
            apps = session.scalars(select(Application).where(Application.candidate_id == document.candidate_id))
            if not any(user.id in session.get(Job, a.job_id).manager_ids for a in apps):
                raise HTTPException(403, "This candidate is not assigned to you")
        from .services.storage import DocumentStorage
        return Response(DocumentStorage(settings).read(document.storage_key), media_type="application/pdf" if document.filename.lower().endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(document.filename), "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/api/applications/{id}/screen", status_code=202)
    def start_screen(id: str, body: schemas.ScreenInput = Body(default_factory=schemas.ScreenInput), user=Depends(recruiter), session=Depends(db_session)):
        application = get_application(session, user, id, lock=True)
        job, candidate = session.get(Job, application.job_id), session.get(Candidate, application.candidate_id)
        if not job.criteria_confirmed:
            raise HTTPException(409, "Confirm the job criteria before screening")
        if not candidate.segments:
            raise HTTPException(409, "Wait for a readable resume or add resume text first")
        previous = list(session.scalars(select(Screening).where(Screening.application_id == id, Screening.criteria_version == job.criteria_version, Screening.profile_version == candidate.profile_version).order_by(Screening.created_at.desc())))
        active = next((result for result in previous if result.status in {"queued", "reviewing", "awaiting_review"}), None)
        expected_engine = {"engine": settings.ai_mode, "model": settings.gemini_model or None if settings.ai_mode == "gemini" else None}
        cached = previous[0] if previous and previous[0].status == "approved" and not body.force and not previous[0].thread_id.startswith("seed-") and screening_engine(session, previous[0]) == expected_engine else None
        reusable = active or cached
        if reusable:
            task = session.scalar(select(BackgroundJob).where(BackgroundJob.payload["screening_id"].as_string() == reusable.id, BackgroundJob.kind.in_(["screen", "screen_review"])).order_by(BackgroundJob.created_at.desc()))
            return {"job_id": task.id if task else None, "screening_id": reusable.id, "status": reusable.status, "cached": True, **screening_engine(session, reusable)}
        screening = Screening(application_id=id, thread_id=uid(), criteria_version=job.criteria_version, profile_version=candidate.profile_version)
        session.add(screening)
        session.flush()
        task = enqueue(session, "screen", {"screening_id": screening.id, "ai_mode": settings.ai_mode, "model": expected_engine["model"]}, id)
        audit(session, user, "screening.started", screening.id)
        session.commit()
        return {"job_id": task.id, "screening_id": screening.id, **expected_engine}

    @app.post("/api/screenings/{id}/review", status_code=202)
    def review_screen(id: str, body: schemas.ReviewInput, user=Depends(recruiter), session=Depends(db_session)):
        screening = session.get(Screening, id)
        if not screening:
            raise HTTPException(404, "Screening not found")
        application = get_application(session, user, screening.application_id, lock=True)
        session.refresh(screening)
        candidate, job = session.get(Candidate, application.candidate_id), session.get(Job, application.job_id)
        if screening.criteria_version != job.criteria_version or screening.profile_version != candidate.profile_version:
            raise HTTPException(409, "Criteria or profile changed. Start a new screening.")
        if screening.status != "awaiting_review":
            raise HTTPException(409, "This screening is not waiting for review")
        screening.status = "reviewing"
        provenance = screening_engine(session, screening)
        task = enqueue(session, "screen_review", {"screening_id": id, "resume": body.model_dump(), "ai_mode": provenance["engine"], "model": provenance["model"]}, application.id)
        audit(session, user, "screening.reviewed", id, approved=body.approved, notes=body.notes)
        session.commit()
        return {"job_id": task.id}

    @app.patch("/api/applications/{id}/stage")
    def move_stage(id: str, body: schemas.StageInput, user=Depends(recruiter), session=Depends(db_session)):
        application = get_application(session, user, id, lock=True)
        if application.stage in {"hired", "rejected", "withdrawn"} and body.stage != application.stage:
            raise HTTPException(409, "This application is closed. Create a new application for a new hiring process.")
        if body.stage in {"hired", "rejected", "withdrawn"} and not body.note:
            raise HTTPException(422, "Record a decision note before closing an application")
        previous = application.stage
        application.stage, application.note, application.updated_at = body.stage, body.note, now()
        audit(session, user, "application.stage_changed", id, **{"from": previous, "to": body.stage, "note": body.note})
        session.commit()
        return serialize(application)

    @app.post("/api/applications/{id}/assessment", status_code=201)
    def invite_assessment(id: str, body: schemas.AssessmentInput, user=Depends(recruiter), session=Depends(db_session)):
        application = get_application(session, user, id, lock=True)
        if session.scalar(select(Assessment).where(Assessment.application_id == id)):
            raise HTTPException(409, "An assessment already exists for this application")
        token = secrets.token_urlsafe(32)
        assessment = Assessment(application_id=id, questions=[q.model_dump() for q in body.questions], token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=now()+timedelta(days=7))
        session.add(assessment)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "An assessment already exists for this application")
        link = settings.frontend_url.rstrip("/") + "/invite/" + token
        action = None
        if body.send_email:
            candidate, job = session.get(Candidate, application.candidate_id), session.get(Job, application.job_id)
            sensitive_payload = {"to": candidate.email, "subject": f"Assessment invitation: {job.title}", "body": f"Hello {candidate.name},\n\nPlease complete the synthetic demo assessment: {link}\n\nThis link expires in seven days. This is a portfolio test, not a real hiring invitation."}
            action = OutboundAction(application_id=id, kind="email", dedupe_key=f"assessment:{assessment.id}", approved_by=user.id, payload={"encrypted": encryption(settings).encrypt(json.dumps(sensitive_payload).encode()).decode()})
            session.add(action)
            session.flush()
            enqueue(session, "email", {"action_id": action.id}, id)
        audit(session, user, "assessment.invited", assessment.id, email_requested=body.send_email)
        session.commit()
        result = serialize(assessment, ("token_hash",))
        result["questions"] = [{k: v for k, v in q.items() if k != "answer"} for q in assessment.questions]
        return {"assessment": result, "invite_url": link, "action_id": action.id if action else None}

    @app.post("/api/assessments/{id}/reinvite")
    def reinvite_assessment(id: str, body: schemas.ReinviteInput = Body(default_factory=schemas.ReinviteInput), user=Depends(recruiter), session=Depends(db_session)):
        assessment = session.get(Assessment, id)
        if not assessment:
            raise HTTPException(404, "Assessment not found")
        application = get_application(session, user, assessment.application_id, lock=True)
        session.refresh(assessment, with_for_update=True)
        if assessment.status != "invited":
            raise HTTPException(409, "A submitted assessment cannot be reinvited")
        active_mail = session.scalar(select(BackgroundJob).where(BackgroundJob.application_id == application.id, BackgroundJob.kind == "email", BackgroundJob.status.in_(["queued", "running"])).limit(1))
        if active_mail:
            raise HTTPException(409, "Wait for the pending invitation email to finish before replacing its link")
        token = secrets.token_urlsafe(32)
        assessment.token_hash = hashlib.sha256(token.encode()).hexdigest()
        assessment.expires_at = now()+timedelta(days=7)
        link = settings.frontend_url.rstrip("/") + "/invite/" + token
        action = None
        if body.send_email:
            candidate, job = session.get(Candidate, application.candidate_id), session.get(Job, application.job_id)
            payload = {"to": candidate.email, "subject": f"New assessment link: {job.title}", "body": f"Hello {candidate.name},\n\nYour replacement synthetic demo assessment link: {link}\n\nThis link expires in seven days. Earlier links are invalid. This is a portfolio test."}
            action = OutboundAction(application_id=application.id, kind="email", dedupe_key=f"assessment-reinvite:{assessment.id}:{assessment.token_hash}", approved_by=user.id, payload={"encrypted": encryption(settings).encrypt(json.dumps(payload).encode()).decode()})
            session.add(action)
            session.flush()
            enqueue(session, "email", {"action_id": action.id}, application.id)
        audit(session, user, "assessment.reinvited", id, email_requested=body.send_email)
        session.commit()
        result = serialize(assessment, ("token_hash",))
        result["questions"] = [{key: value for key, value in question.items() if key != "answer"} for question in assessment.questions]
        return {"assessment": result, "invite_url": link, "action_id": action.id if action else None}

    def invitation(session, token):
        if len(token) > 150:
            raise HTTPException(404, "Invitation not found")
        assessment = session.scalar(select(Assessment).where(Assessment.token_hash == hashlib.sha256(token.encode()).hexdigest()))
        if not assessment:
            raise HTTPException(404, "Invitation not found")
        expires = as_utc(assessment.expires_at)
        if expires < now():
            raise HTTPException(410, "This invitation has expired. Ask the recruiter for a new assessment.")
        return assessment

    @app.get("/api/invitations/{token}")
    def read_invitation(token: str, session=Depends(db_session)):
        assessment = invitation(session, token)
        application = session.get(Application, assessment.application_id)
        job = session.get(Job, application.job_id)
        if assessment.status != "invited":
            return {"submitted": True, "status": assessment.status, "job_title": job.title}
        return {"id": assessment.id, "submitted": False, "job_title": job.title, "expires_at": as_utc(assessment.expires_at).isoformat(), "questions": [{k: v for k, v in q.items() if k not in {"answer", "rubric"}} for q in assessment.questions]}

    @app.post("/api/invitations/{token}")
    def submit_invitation(token: str, body: schemas.InvitationSubmission, session=Depends(db_session)):
        assessment = invitation(session, token)
        if assessment.status != "invited":
            raise HTTPException(409, "This assessment has already been submitted")
        if set(body.answers) != {q["id"] for q in assessment.questions} or any(not answer.strip() for answer in body.answers.values()):
            raise HTTPException(422, "Answer every assessment question exactly once")
        mcqs = [q for q in assessment.questions if q["kind"] == "mcq"]
        for question in mcqs:
            if body.answers[question["id"]] not in question["options"]:
                raise HTTPException(422, "Select one of the listed options for each MCQ")
        if any(window.start < now() for window in body.availability):
            raise HTTPException(422, "Availability must be in the future")
        score = round(sum(body.answers[q["id"]] == q["answer"] for q in mcqs)/len(mcqs)*100, 1) if mcqs else None
        changed = session.execute(update(Assessment).execution_options(synchronize_session=False).where(Assessment.id == assessment.id, Assessment.status == "invited", Assessment.token_hash == hashlib.sha256(token.encode()).hexdigest(), Assessment.expires_at >= now()).values(status="submitted", submitted_at=now(), answers=body.answers, availability=[v.model_dump(mode="json") for v in body.availability], mcq_score=score))
        if changed.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "This invitation has changed, expired, or already been submitted. Refresh the page or ask the recruiter for the current link.")
        task = enqueue(session, "assessment_feedback", {"assessment_id": assessment.id}, assessment.application_id)
        audit(session, None, "assessment.submitted", assessment.id)
        session.commit()
        return {"submitted": True, "message": "Your responses and availability have been recorded.", "job_id": task.id}

    @app.post("/api/assessments/{id}/review")
    def review_assessment(id: str, body: schemas.NotesInput, user=Depends(recruiter), session=Depends(db_session)):
        assessment = session.get(Assessment, id)
        if not assessment:
            raise HTTPException(404, "Assessment not found")
        get_application(session, user, assessment.application_id)
        if assessment.status not in {"submitted", "reviewed"}:
            raise HTTPException(409, "Wait for the candidate to submit this assessment")
        assessment.status, assessment.review_notes, assessment.reviewed_at = "reviewed", body.notes, now()
        audit(session, user, "assessment.reviewed", id)
        session.commit()
        return serialize(assessment, ("token_hash", "questions"))

    @app.post("/api/applications/{id}/interviews", status_code=202)
    def schedule_interview(id: str, body: schemas.InterviewInput, user=Depends(recruiter), session=Depends(db_session)):
        application = get_application(session, user, id, lock=True)
        if body.start < now():
            raise HTTPException(422, "Interview start must be in the future")
        if (body.end-body.start).total_seconds() > 3*3600:
            raise HTTPException(422, "Interviews must not exceed three hours")
        start, end = body.start.astimezone(timezone.utc), body.end.astimezone(timezone.utc)
        dedupe = "interview:" + hashlib.sha256(f"{id}|{start.isoformat()}|{end.isoformat()}".encode()).hexdigest()
        existing = session.scalar(select(OutboundAction).where(OutboundAction.dedupe_key == dedupe))
        if existing:
            task = session.scalar(select(BackgroundJob).where(BackgroundJob.application_id == id, BackgroundJob.kind == "interview", BackgroundJob.payload["action_id"].as_string() == existing.id).order_by(BackgroundJob.created_at.desc()))
            return {"job_id": task.id, "action_id": existing.id, "cached": True}
        action_id = uid()
        interview = Interview(application_id=id, start=start, end=end, timezone=body.timezone, action_id=action_id)
        session.add(interview)
        session.flush()
        job, candidate = session.get(Job, application.job_id), session.get(Candidate, application.candidate_id)
        attendees = [address.strip() for address in settings.calendar_allowed_emails.split(",") if address.strip()]
        if settings.external_mode == "live" and not attendees:
            raise HTTPException(409, "Configure owned test attendee addresses before live scheduling")
        action = OutboundAction(id=action_id, application_id=id, kind="interview", dedupe_key=dedupe, approved_by=user.id, payload={"interview_id": interview.id, "attendees": attendees, "summary": f"[Synthetic demo] {job.title} · {candidate.name}", "intended_candidate": candidate.email})
        session.add(action)
        session.flush()
        task = enqueue(session, "interview", {"action_id": action.id}, id)
        audit(session, user, "interview.approved", interview.id, start=start.isoformat())
        session.commit()
        return {"job_id": task.id, "interview_id": interview.id, "action_id": action.id}

    @app.post("/api/applications/{id}/feedback", status_code=201)
    def add_feedback(id: str, body: schemas.FeedbackInput, user=Depends(current_user), session=Depends(db_session)):
        get_application(session, user, id)
        feedback = Feedback(application_id=id, user_id=user.id, **body.model_dump())
        session.add(feedback)
        session.flush()
        audit(session, user, "feedback.recorded", id)
        session.commit()
        return serialize(feedback)

    @app.get("/api/background-jobs/{id}")
    def background_status(id: str, user=Depends(current_user), session=Depends(db_session)):
        task = session.get(BackgroundJob, id)
        if not task:
            raise HTTPException(404, "Processing task not found")
        if task.application_id:
            get_application(session, user, task.application_id)
        elif user.role == "manager":
            raise HTTPException(403, "This task is not assigned to you")
        return serialize(task, ("payload", "lease_until", "next_attempt_at"))

    @app.post("/api/background-jobs/{id}/retry", status_code=202)
    def retry_task(id: str, user=Depends(recruiter), session=Depends(db_session)):
        if session.get_bind().dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        task = session.scalar(select(BackgroundJob).where(BackgroundJob.id == id).with_for_update())
        if not task:
            raise HTTPException(404, "Processing task not found")
        if task.status != "failed" or task.kind in {"interview", "screen_review"}:
            raise HTTPException(409, "This task cannot be retried automatically. Review the error and provider state first.")
        if task.application_id:
            get_application(session, user, task.application_id)
        if task.kind == "email":
            action = session.get(OutboundAction, task.payload.get("action_id"))
            if not action or action.status != "failed" or not action.payload.get("encrypted"):
                raise HTTPException(409, "Delivery is uncertain or already completed. Reconcile the provider log before resending.")
            action.status, action.error, action.approved_by = "approved", None, user.id
        task.status, task.error, task.next_attempt_at, task.attempts = "queued", None, now(), 0
        if task.kind == "import":
            session.get(Document, task.payload["document_id"]).status = "queued"
        if task.kind == "screen":
            session.get(Screening, task.payload["screening_id"]).status = "queued"
        audit(session, user, "task.retried", id)
        session.commit()
        return {"job_id": task.id}

    @app.get("/api/integrations")
    def integration_status(user=Depends(current_user), session=Depends(db_session)):
        state = session.scalar(select(IntegrationState).where(IntegrationState.provider == "google_calendar"))
        return {"ai_mode": settings.ai_mode, "external_mode": settings.external_mode, "gemini": {"configured": bool(settings.gemini_api_key and settings.gemini_model), "model": settings.gemini_model or None}, "email": {"configured": bool(settings.resend_api_key and settings.resend_test_inbox), "mode": settings.external_mode, "test_inbox": settings.resend_test_inbox if user.role == "admin" else None}, "calendar": {"configured": bool(settings.google_client_id and settings.google_client_secret), "status": state.status if state else "disconnected", "mode": settings.external_mode}, "storage": "supabase" if settings.supabase_url and settings.supabase_service_role_key else "local", "processing": "One task at a time; processing resumes after a sleeping service wakes."}

    @app.get("/api/integrations/calendar/connect")
    def connect_calendar(user=Depends(admin), session=Depends(db_session)):
        from .services.integrations import Integrations
        state_value = secrets.token_urlsafe(32)
        token = jwt.encode({"sub": user.id, "nonce": state_value, "purpose": "calendar_oauth", "exp": now()+timedelta(minutes=10)}, settings.app_secret, algorithm="HS256")
        pending = session.scalar(select(IntegrationState).where(IntegrationState.provider == "google_oauth_pending"))
        if not pending:
            pending = IntegrationState(provider="google_oauth_pending")
            session.add(pending)
        pending.encrypted_tokens, pending.connected_by, pending.status, pending.expires_at = hashlib.sha256(token.encode()).hexdigest(), user.id, "pending", now()+timedelta(minutes=10)
        session.commit()
        try:
            return {"url": Integrations(settings).authorization_url(token)}
        except Exception as error:
            raise HTTPException(409, str(error)[:400])

    @app.get("/api/integrations/calendar/callback")
    def calendar_callback(state: str, code: str | None = None, error: str | None = None, session=Depends(db_session)):
        try:
            claims = jwt.decode(state, settings.app_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
            if claims.get("purpose") != "calendar_oauth":
                raise ValueError("Invalid OAuth purpose")
            pending = session.scalar(select(IntegrationState).where(IntegrationState.provider == "google_oauth_pending"))
            if not pending or pending.status != "pending" or not secrets.compare_digest(pending.encrypted_tokens, hashlib.sha256(state.encode()).hexdigest()):
                raise ValueError("OAuth request already used or unknown")
            staff_user = session.get(User, claims["sub"])
            if not staff_user or staff_user.role != "admin":
                raise ValueError("Admin access expired")
            pending.status = "consumed"
            session.commit()
        except (jwt.PyJWTError, ValueError, KeyError):
            raise HTTPException(400, "Calendar connection request expired or invalid. Start again from Settings.")
        if error or not code:
            return RedirectResponse(settings.frontend_url.rstrip("/") + "/settings?calendar=denied")
        from .services.integrations import Integrations
        try:
            tokens = Integrations(settings).exchange_code(code)
            current = session.scalar(select(IntegrationState).where(IntegrationState.provider == "google_calendar"))
            if not current:
                current = IntegrationState(provider="google_calendar")
                session.add(current)
            current.encrypted_tokens = encryption(settings).encrypt(json.dumps(tokens).encode()).decode()
            current.connected_by, current.status = claims["sub"], "connected"
            current.expires_at = now()+timedelta(seconds=int(tokens.get("expires_in", 3600)))
            audit(session, staff_user, "calendar.connected", current.id or "calendar")
            session.commit()
        except Exception:
            return RedirectResponse(settings.frontend_url.rstrip("/") + "/settings?calendar=failed")
        return RedirectResponse(settings.frontend_url.rstrip("/") + "/settings?calendar=connected")

    @app.get("/api/integrations/calendar/freebusy")
    def freebusy(start: datetime, end: datetime, user=Depends(recruiter), session=Depends(db_session)):
        if start.tzinfo is None or end.tzinfo is None or end <= start or (end-start).total_seconds() > 7 * 86400:
            raise HTTPException(422, "Provide a timezone-aware window of at most seven days")
        from .services.integrations import Integrations
        integrations = Integrations(settings)
        tokens = {}
        try:
            tokens = calendar_tokens(session, settings, integrations)
            result = integrations.freebusy(tokens, start.isoformat(), end.isoformat())
            persist_calendar_tokens(session, settings, tokens)
            return result
        except Exception as error:
            persist_calendar_tokens(session, settings, tokens)
            mark_calendar_error(session, error)
            raise HTTPException(409, str(error)[:400])

    @app.post("/api/demo/reset")
    def reset_demo(user=Depends(admin), session=Depends(db_session)):
        if settings.app_env == "production" and not settings.enable_demo_reset:
            raise HTTPException(403, "Demo reset is disabled on this deployment")
        if session.scalar(select(BackgroundJob).where(BackgroundJob.status.in_(["queued", "running"])).limit(1)):
            raise HTTPException(409, "Wait for active processing tasks to finish before resetting the demo")
        from .services.storage import DocumentStorage
        storage = DocumentStorage(settings)
        for document in session.scalars(select(Document)):
            storage.delete(document.storage_key)
        for model in [AuditEvent, BackgroundJob, OutboundAction, Interview, Feedback, Assessment, Screening, Application, Document, Candidate, Job]:
            session.execute(delete(model))
        session.commit()
        seed_database(session, settings)
        audit(session, user, "demo.reset", "workspace")
        session.commit()
        return {"reset": True}

    return app


app = create_app()
