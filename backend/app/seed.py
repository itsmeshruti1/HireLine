"""Idempotent, explicitly synthetic development/demo data."""
from datetime import timedelta
from pathlib import Path
import hashlib
import json
from sqlalchemy import select
from .db import now
from .models import User, Job, Candidate, Application, Screening, AuditEvent, Document


STAFF = [("admin-demo", "admin@demo.local", "Alex Morgan", "admin"), ("recruiter-demo", "recruiter@demo.local", "Sam Taylor", "recruiter"), ("manager-demo", "manager@demo.local", "Jordan Lee", "manager")]


def seed_database(session, settings):
    if settings.auth_mode == "local":
        for id, email, name, role in STAFF:
            if not session.get(User, id):
                session.add(User(id=id, email=email, name=name, role=role))
        session.commit()
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic.json"
    if not fixture.exists():
        return
    data = json.loads(fixture.read_text(encoding="utf-8"))
    for row in data["jobs"]:
        if not session.get(Job, row["id"]):
            session.add(Job(id=row["id"], title=row["title"], department=row.get("department", "Engineering"), location=row.get("location", "Remote"), description=row["description"], criteria=row["criteria"], criteria_confirmed=True, criteria_version=1, manager_ids=["manager-demo"] if settings.auth_mode == "local" else [], created_at=now() - timedelta(days=14)))
    session.commit()
    from .services.ai import evaluate
    from .services.screening import verified_score
    from .services.storage import DocumentStorage
    storage = DocumentStorage(settings)
    for index, row in enumerate(data["candidates"]):
        if session.get(Candidate, row["id"]):
            continue
        created = now() - timedelta(days=12 - index % 10)
        candidate = Candidate(id=row["id"], name=row["name"], email=row.get("email", ""), headline=row.get("headline", ""), skills=row.get("skills", []), experience_years=row.get("experience_years"), location=row.get("location", "Remote"), notice_period_days=row.get("notice_period_days"), salary_expectation=row.get("salary_expectation", ""), segments=row.get("segments", [{"id": "page-1", "text": row["resume_text"]}]), profile_version=1, created_at=created)
        session.add(candidate)
        session.flush()
        sample = Path(__file__).resolve().parents[2] / row.get("sample_file", "")
        if sample.is_file():
            content = sample.read_bytes()
            key = f"{candidate.id}/{sample.name}"
            storage.put(key, content, "application/pdf" if sample.suffix == ".pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            session.add(Document(candidate_id=candidate.id, filename=sample.name, storage_key=key, content_hash=hashlib.sha256(content).hexdigest(), segments=candidate.segments, status="ready", created_at=created))
        application = Application(id=f"application-{index+1:02}", candidate_id=candidate.id, job_id=row.get("job_id", data["jobs"][index % len(data["jobs"])]["id"]), stage=row.get("stage", "new"), created_at=created, updated_at=created + timedelta(days=1))
        session.add(application)
        session.flush()
        job = session.get(Job, application.job_id)
        result = verified_score(candidate.segments, job.criteria, evaluate(candidate.segments, job.criteria, mode="demo"))
        session.add(Screening(id=f"screening-{index+1:02}", application_id=application.id, thread_id=f"seed-{application.id}", criteria_version=job.criteria_version, profile_version=1, matches=result["matches"], score=result["score"], missing_count=result["missing_count"], status="approved", review_notes="Synthetic sample result. Run a new screening to exercise the review workflow.", reviewed_at=created + timedelta(days=1), created_at=created))
        session.add(AuditEvent(actor_id="recruiter-demo", action="application.created", entity_id=application.id, details={"stage": "new", "synthetic": True}, created_at=created))
        if application.stage != "new":
            session.add(AuditEvent(actor_id="recruiter-demo", action="application.stage_changed", entity_id=application.id, details={"from": "new", "to": application.stage, "note": "Synthetic sample timeline"}, created_at=created + timedelta(days=1)))
    session.commit()
