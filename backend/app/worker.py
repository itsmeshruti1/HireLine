from datetime import timedelta, timezone
import json
import logging
import threading
from sqlalchemy import and_, or_, select, update
from .db import as_utc, now
from .models import Application, Assessment, BackgroundJob, Candidate, Document, IntegrationState, Interview, Job, OutboundAction, Screening
from .auth import encryption


logger = logging.getLogger(__name__)


def enqueue(session, kind, payload, application_id=None):
    task = BackgroundJob(kind=kind, payload=payload, application_id=application_id)
    session.add(task)
    session.flush()
    return task


def claim_job(session):
    eligible = or_(and_(BackgroundJob.status == "queued", BackgroundJob.next_attempt_at <= now()), and_(BackgroundJob.status == "running", BackgroundJob.lease_until < now()))
    task = session.scalar(select(BackgroundJob).where(eligible).order_by(BackgroundJob.created_at).limit(1).with_for_update(skip_locked=True))
    if task is None:
        return None
    task.status = "running"
    task.attempts += 1
    task.lease_until = now() + timedelta(seconds=120)
    task.updated_at = now()
    session.commit()
    return task.id


def calendar_tokens(session, settings, integrations):
    if settings.external_mode == "preview":
        return {}
    state = session.scalar(select(IntegrationState).where(IntegrationState.provider == "google_calendar"))
    if not state or state.status != "connected":
        if settings.external_mode == "preview":
            return {}
        raise ValueError("Google Calendar is disconnected. Reconnect it in Settings.")
    tokens = json.loads(encryption(settings).decrypt(state.encrypted_tokens.encode()).decode())
    expires = state.expires_at
    if expires and as_utc(expires) < now() + timedelta(seconds=60):
        try:
            updated = integrations.refresh_tokens(tokens)
            tokens.update(updated)
            persist_calendar_tokens(session, settings, tokens)
        except Exception as error:
            mark_calendar_error(session, error)
            raise
    return tokens


def mark_calendar_error(session, error):
    if getattr(error, "reconnect_required", False):
        state = session.scalar(select(IntegrationState).where(IntegrationState.provider == "google_calendar"))
        if state:
            state.status = "reconnect_required"
            session.commit()


def persist_calendar_tokens(session, settings, tokens):
    if not tokens or settings.external_mode == "preview":
        return
    state = session.scalar(select(IntegrationState).where(IntegrationState.provider == "google_calendar"))
    if not state:
        return
    state.encrypted_tokens = encryption(settings).encrypt(json.dumps(tokens).encode()).decode()
    if tokens.get("expires_at"):
        from datetime import datetime
        state.expires_at = datetime.fromisoformat(tokens["expires_at"].replace("Z", "+00:00"))
    else:
        state.expires_at = now()+timedelta(seconds=int(tokens.get("expires_in", 3600)))
    session.commit()


def execute_task(session_factory, settings, task_id):
    from .services.ai import extract_profile
    from .services.documents import extract_document
    from .services.screening import run_screening
    from .services.storage import DocumentStorage
    from .services.integrations import Integrations

    with session_factory() as session:
        task = session.get(BackgroundJob, task_id)
        result = {}
        if task.kind == "import":
            document = session.get(Document, task.payload["document_id"])
            candidate = session.get(Candidate, document.candidate_id)
            if document.status == "ready":
                result = {"candidate_id": candidate.id, "cached": True}
            else:
                cached = session.scalar(select(Document).where(Document.content_hash == document.content_hash, Document.status == "ready").limit(1))
                segments = cached.segments if cached else extract_document(document.filename, DocumentStorage(settings).read(document.storage_key))
                if not segments or not any(s.get("text", "").strip() for s in segments):
                    raise ValueError("No readable text found. Scanned PDFs need OCR; upload a text-based PDF or DOCX.")
                cache_key = f"profile-v1:{settings.ai_mode}:{settings.gemini_model}"
                cached_task = session.scalar(select(BackgroundJob).where(BackgroundJob.kind == "import", BackgroundJob.status == "completed", BackgroundJob.result["content_hash"].as_string() == document.content_hash, BackgroundJob.result["cache_key"].as_string() == cache_key).limit(1))
                if cached_task and cached_task.result.get("_profile"):
                    profile = cached_task.result["_profile"]
                elif cached and settings.ai_mode == "demo" and session.get(Candidate, cached.candidate_id).profile_version == 1:
                    source = session.get(Candidate, cached.candidate_id)
                    profile = {key: getattr(source, key) for key in ["name", "email", "headline", "skills", "experience_years", "location", "notice_period_days", "salary_expectation"]}
                else:
                    profile = extract_profile(segments, mode=settings.ai_mode)
                allowed = {"name", "email", "headline", "skills", "experience_years", "location", "notice_period_days", "salary_expectation"}
                for key, value in profile.items():
                    if key in allowed and value is not None:
                        setattr(candidate, key, value)
                candidate.segments = segments
                document.segments = segments
                document.status = "ready"
                document.error = None
                result = {"candidate_id": candidate.id, "document_id": document.id, "content_hash": document.content_hash, "cache_key": cache_key, "_profile": profile}
        elif task.kind in {"screen", "screen_review"}:
            screening = session.get(Screening, task.payload["screening_id"])
            application = session.get(Application, screening.application_id)
            candidate = session.get(Candidate, application.candidate_id)
            job = session.get(Job, application.job_id)
            if screening.criteria_version != job.criteria_version or screening.profile_version != candidate.profile_version:
                screening.status = "stale"
                raise ValueError("The job criteria or candidate profile changed. Start a new screening.")
            if not candidate.segments:
                raise ValueError("This candidate has no readable resume text. Upload a resume first.")
            engine = task.payload.get("ai_mode", settings.ai_mode)
            model = task.payload.get("model") if engine == "gemini" else None
            if task.kind == "screen" and (engine != settings.ai_mode or model != (settings.gemini_model or None if settings.ai_mode == "gemini" else None)):
                raise ValueError("The AI provider or model changed while screening was queued. Start a new screening.")
            if "ai_mode" not in task.payload:
                task.payload = {**task.payload, "ai_mode": engine, "model": model}
                session.commit()
            data = run_screening(screening.thread_id, candidate.segments, job.criteria, settings.checkpoint_url, mode=engine, resume=task.payload.get("resume"))
            # A recruiter may edit the source or rubric while the model is running.
            session.refresh(job)
            session.refresh(candidate)
            session.refresh(screening)
            if screening.criteria_version != job.criteria_version or screening.profile_version != candidate.profile_version:
                raise ValueError("The job criteria or candidate profile changed during screening. Start a new screening.")
            screening.matches = data.get("matches", [])
            screening.score = data.get("score", 0)
            screening.missing_count = data.get("missing_count", 0)
            screening.status = "awaiting_review" if data.get("awaiting_review") else ("approved" if data.get("approved") else "rejected")
            if screening.status in {"approved", "rejected"}:
                screening.reviewed_at = now()
                screening.review_notes = task.payload.get("resume", {}).get("notes", "")
            result = {"screening_id": screening.id, "status": screening.status}
        elif task.kind == "assessment_feedback":
            assessment = session.get(Assessment, task.payload["assessment_id"])
            from .services.ai import assess_short_answers
            assessment.short_answer_feedback = assess_short_answers(assessment.questions, assessment.answers, mode=settings.ai_mode)
            result = {"assessment_id": assessment.id}
        elif task.kind in {"email", "interview"}:
            action = session.get(OutboundAction, task.payload["action_id"])
            if action.status in {"sent", "preview"}:
                result = {"action_id": action.id, "status": action.status, "cached": True}
            elif action.status in {"sending", "needs_reconciliation"} and task.kind == "email":
                action.status = "needs_reconciliation"
                session.commit()
                raise ValueError("Email delivery is uncertain. Inspect the provider log before retrying; automatic resend is disabled.")
            else:
                integrations = Integrations(settings)
                action.status = "sending"
                session.commit()
                try:
                    if task.kind == "email":
                        payload = json.loads(encryption(settings).decrypt(action.payload["encrypted"].encode()).decode())
                        response = integrations.send_email(action.id, payload["to"], payload["subject"], payload["body"])
                    else:
                        interview = session.get(Interview, action.payload["interview_id"])
                        tokens = calendar_tokens(session, settings, integrations)
                        start = as_utc(interview.start).isoformat()
                        end = as_utc(interview.end).isoformat()
                        try:
                            response = integrations.create_event(action.id, tokens, start, end, action.payload["attendees"], summary=action.payload["summary"], timezone=interview.timezone)
                        except Exception as error:
                            persist_calendar_tokens(session, settings, tokens)
                            mark_calendar_error(session, error)
                            raise
                        persist_calendar_tokens(session, settings, tokens)
                        interview.status = response.get("status", "sent")
                        interview.provider_id = response.get("id")
                    action.status = response.get("status", "sent")
                    action.provider_id = response.get("id")
                    action.result = {key: value for key, value in response.items() if key != "body"}
                    if task.kind == "email":
                        action.payload = {}
                    action.error = None
                    result = {"action_id": action.id, "status": action.status}
                except Exception as error:
                    from .services.errors import ServiceError
                    known_not_delivered = isinstance(error, ServiceError) and not error.ambiguous
                    action.status = "needs_reconciliation" if task.kind == "email" and not known_not_delivered else "failed"
                    action.error = str(error)[:1000]
                    if task.kind == "interview":
                        session.get(Interview, action.payload["interview_id"]).status = "failed"
                    session.commit()
                    raise
        else:
            raise ValueError(f"Unsupported background task: {task.kind}")
        task.status = "completed"
        task.result = result
        task.error = None
        task.lease_until = None
        task.updated_at = now()
        session.commit()


def process_one(session_factory, settings):
    with session_factory() as session:
        task_id = claim_job(session)
    if not task_id:
        return False
    try:
        execute_task(session_factory, settings, task_id)
    except Exception as error:
        logger.warning("Background task %s failed: %s", task_id, type(error).__name__)
        with session_factory() as session:
            task = session.get(BackgroundJob, task_id)
            transient = getattr(error, "retryable", False)
            if transient and task.attempts < 3 and task.kind not in {"email", "interview"}:
                task.status = "queued"
                task.next_attempt_at = now() + timedelta(seconds=5 * 2 ** task.attempts)
            else:
                task.status = "failed"
            task.error = str(error)[:1000]
            task.lease_until = None
            task.updated_at = now()
            if task.kind == "import":
                document = session.get(Document, task.payload["document_id"])
                document.status = "failed"
                document.error = task.error
            if task.kind in {"screen", "screen_review"}:
                screening = session.get(Screening, task.payload["screening_id"])
                application = session.get(Application, screening.application_id)
                candidate = session.get(Candidate, application.candidate_id)
                job = session.get(Job, application.job_id)
                screening.status = "stale" if screening.criteria_version != job.criteria_version or screening.profile_version != candidate.profile_version else "failed"
            session.commit()
    return True


def worker_loop(session_factory, settings, stop: threading.Event):
    while not stop.is_set():
        try:
            worked = process_one(session_factory, settings)
        except Exception:
            logger.exception("Worker polling failed")
            worked = False
        if not worked:
            stop.wait(.5)
