from datetime import datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.strip()


class Criterion(Input):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=2, max_length=500)
    weight: float = Field(gt=0, le=100)


class JobInput(Input):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=10, max_length=30000)
    department: str = Field(default="Engineering", max_length=100)
    location: str = Field(default="Remote", max_length=120)
    criteria: list[Criterion] = Field(default_factory=list, max_length=12)
    criteria_confirmed: bool = False
    manager_ids: list[str] = Field(default_factory=list, max_length=20)


class JobPatch(Input):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, min_length=10, max_length=30000)
    department: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=120)
    status: Literal["open", "closed", "draft"] | None = None
    criteria: list[Criterion] | None = Field(default=None, min_length=1, max_length=12)
    criteria_confirmed: bool | None = None
    manager_ids: list[str] | None = Field(default=None, max_length=20)


class DraftInput(Input):
    description: str = Field(min_length=10, max_length=30000)


class CandidateInput(Input):
    name: str = Field(min_length=2, max_length=160)
    email: str = Field(default="", max_length=254)
    headline: str = Field(default="", max_length=300)
    skills: list[str] = Field(default_factory=list, max_length=100)
    experience_years: float | None = Field(default=None, ge=0, le=80)
    location: str = Field(default="", max_length=120)
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    salary_expectation: str = Field(default="", max_length=120)
    resume_text: str = Field(default="", max_length=100000)
    synthetic_confirmed: bool = False


class CandidatePatch(Input):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    headline: str | None = Field(default=None, max_length=300)
    skills: list[str] | None = Field(default=None, max_length=100)
    experience_years: float | None = Field(default=None, ge=0, le=80)
    location: str | None = Field(default=None, max_length=120)
    notice_period_days: int | None = Field(default=None, ge=0, le=365)
    salary_expectation: str | None = Field(default=None, max_length=120)
    resume_text: str | None = Field(default=None, max_length=100000)


class ApplicationInput(Input):
    candidate_id: str


class StageInput(Input):
    stage: Literal["new", "screening", "shortlisted", "assessment", "interview", "hired", "rejected", "withdrawn"]
    note: str = Field(default="", max_length=4000)


class ReviewInput(Input):
    approved: bool
    notes: str = Field(default="", max_length=4000)


class ScreenInput(Input):
    force: bool = False


class NotesInput(Input):
    notes: str = Field(min_length=1, max_length=4000)


class Question(Input):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["mcq", "short"]
    prompt: str = Field(min_length=3, max_length=2000)
    options: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]] = Field(default_factory=list, max_length=10)
    answer: str | None = Field(default=None, max_length=2000)
    rubric: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def check_question(self):
        if self.kind == "mcq" and (len(self.options) < 2 or self.answer not in self.options):
            raise ValueError("MCQs require at least two options and an answer matching one option")
        if len(set(self.options)) != len(self.options):
            raise ValueError("Question options must be unique")
        if self.kind == "short" and not self.rubric:
            raise ValueError("Short-answer questions require a review rubric")
        return self


class AssessmentInput(Input):
    questions: list[Question] = Field(min_length=1, max_length=12)
    send_email: bool = False

    @field_validator("questions")
    @classmethod
    def unique_ids(cls, value):
        if len({q.id for q in value}) != len(value):
            raise ValueError("Question IDs must be unique")
        return value


class ReinviteInput(Input):
    send_email: bool = False


class Availability(Input):
    start: datetime
    end: datetime
    timezone: str = "UTC"

    @model_validator(mode="after")
    def time_window(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Times must include a UTC offset")
        if self.end <= self.start:
            raise ValueError("End must be after start")
        if (self.end - self.start).total_seconds() > 8 * 3600:
            raise ValueError("Availability windows must not exceed eight hours")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Use a valid IANA timezone")
        return self


class InvitationSubmission(Input):
    answers: dict[str, str] = Field(max_length=12)
    availability: list[Availability] = Field(default_factory=list, max_length=10)

    @field_validator("answers")
    @classmethod
    def bound_answers(cls, value):
        if any(len(k) > 80 or len(v) > 10000 for k, v in value.items()):
            raise ValueError("Answer too long")
        return value


class InterviewInput(Availability):
    pass


class FeedbackInput(Input):
    rating: int = Field(ge=1, le=5)
    notes: str = Field(min_length=3, max_length=4000)
