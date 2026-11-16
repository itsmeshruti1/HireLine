from datetime import datetime
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, now, uid


class Identity:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Identity, Base):
    __tablename__ = "staff_users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(32))


class Job(Identity, Base):
    __tablename__ = "jobs"
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(100), default="Engineering")
    location: Mapped[str] = mapped_column(String(120), default="Remote")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="open")
    criteria: Mapped[list] = mapped_column(JSON, default=list)
    criteria_version: Mapped[int] = mapped_column(Integer, default=1)
    criteria_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    manager_ids: Mapped[list] = mapped_column(JSON, default=list)


class Candidate(Identity, Base):
    __tablename__ = "candidates"
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254), default="")
    headline: Mapped[str] = mapped_column(String(300), default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    location: Mapped[str] = mapped_column(String(120), default="")
    notice_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_expectation: Mapped[str] = mapped_column(String(120), default="")
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    segments: Mapped[list] = mapped_column(JSON, default=list)


class Document(Identity, Base):
    __tablename__ = "documents"
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(300))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    segments: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Application(Identity, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("job_id", "candidate_id"),)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("candidates.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32), default="new")
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Screening(Identity, Base):
    __tablename__ = "screenings"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(120), unique=True)
    criteria_version: Mapped[int] = mapped_column(Integer)
    profile_version: Mapped[int] = mapped_column(Integer)
    matches: Mapped[list] = mapped_column(JSON, default=list)
    score: Mapped[float] = mapped_column(Float, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    review_notes: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Assessment(Identity, Base):
    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("application_id"),)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    questions: Mapped[list] = mapped_column(JSON, default=list)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="invited")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mcq_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    short_answer_feedback: Mapped[list] = mapped_column(JSON, default=list)
    review_notes: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    availability: Mapped[list] = mapped_column(JSON, default=list)


class Interview(Identity, Base):
    __tablename__ = "interviews"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    provider_id: Mapped[str | None] = mapped_column(String(250), nullable=True)
    action_id: Mapped[str] = mapped_column(String(64), unique=True)


class Feedback(Identity, Base):
    __tablename__ = "feedback"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("staff_users.id"))
    rating: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text)


class BackgroundJob(Identity, Base):
    __tablename__ = "background_jobs"
    kind: Mapped[str] = mapped_column(String(40))
    application_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutboundAction(Identity, Base):
    __tablename__ = "outbound_actions"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="approved")
    dedupe_key: Mapped[str] = mapped_column(String(180), unique=True)
    approved_by: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str | None] = mapped_column(String(250), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Identity, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class IntegrationState(Identity, Base):
    __tablename__ = "integration_states"
    provider: Mapped[str] = mapped_column(String(40), unique=True)
    encrypted_tokens: Mapped[str] = mapped_column(Text, default="")
    connected_by: Mapped[str] = mapped_column(String(64), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="disconnected")
