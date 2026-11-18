import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Copy,
  ExternalLink,
  FileText,
  Loader2,
  Plus,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { api, patch, post, tokenStore } from "./api";
import {
  getCandidate,
  getJob,
  latestScreening,
  screeningScore,
  STAGES,
  useApp,
} from "./context";
import type { ModalState } from "./context";
import type {
  Application,
  Candidate,
  Criterion,
  Job,
  Question,
  User,
} from "./types";
import { Avatar, Badge, Button, date, label, Modal, Score } from "./ui";

type FormShellProps = {
  children: ReactNode;
  onSubmit: () => Promise<void>;
  submit: string;
  success?: string;
  closeAfter?: boolean;
  wide?: boolean;
  disabled?: boolean;
};
function FormShell({
  children,
  onSubmit,
  submit,
  success,
  closeAfter = true,
  disabled = false,
}: FormShellProps) {
  const { close, refresh, notify } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function handle(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onSubmit();
      if (success) notify(success);
      await refresh();
      if (closeAfter) close();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={handle} className="workspace-form">
      <div className="form-fields">
        {children}
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
      </div>
      <footer className="form-footer">
        <Button type="button" variant="secondary" onClick={close}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy || disabled}>
          {busy ? <Loader2 size={16} className="spin" /> : null}
          {busy ? "Working…" : submit}
          {!busy && <ArrowRight size={14} />}
        </Button>
      </footer>
    </form>
  );
}

export function ModalHost({ state }: { state: NonNullable<ModalState> }) {
  const { close } = useApp();
  const titles: Record<string, [string, string]> = {
    login: ["Welcome back", "STAFF SIGN IN"],
    job: [
      state.job ? "Edit job and rubric" : "Create a job opening",
      "JOB OPENING",
    ],
    upload: ["Import resumes", "IMPORT SYNTHETIC RESUMES"],
    profile: ["Edit candidate profile", "CANDIDATE PROFILE"],
    stage: ["Update application stage", "UPDATE APPLICATION"],
    assessment: ["Create assessment", "CANDIDATE ASSESSMENT"],
    reinvite: ["A fresh invitation", "RENEW CANDIDATE ACCESS"],
    schedule: ["Schedule an interview", "SCHEDULE INTERVIEW"],
    feedback: ["Record interview feedback", "HIRING TEAM FEEDBACK"],
    review: ["Review screening", "SCREENING REVIEW"],
    "assessment-review": ["Review their responses", "ASSESSMENT REVIEW"],
    compare: ["Compare candidate evidence", "COMPARE CANDIDATES"],
  };
  const [title, eyebrow] = titles[state.kind];
  return (
    <Modal
      title={title}
      eyebrow={eyebrow}
      onClose={close}
      wide={["job", "assessment", "compare"].includes(state.kind)}
    >
      {state.kind === "login" ? (
        <LoginForm />
      ) : state.kind === "job" ? (
        <JobForm job={state.job} />
      ) : state.kind === "upload" ? (
        <UploadForm job={state.job} />
      ) : state.kind === "profile" && state.candidate ? (
        <ProfileForm candidate={state.candidate} />
      ) : state.kind === "stage" && state.application ? (
        <StageForm application={state.application} />
      ) : state.kind === "review" && state.screeningId ? (
        <ScreeningReview screeningId={state.screeningId} />
      ) : state.kind === "assessment" && state.application ? (
        <AssessmentForm application={state.application} />
      ) : state.kind === "reinvite" && state.assessmentId ? (
        <ReinviteForm assessmentId={state.assessmentId} />
      ) : state.kind === "assessment-review" && state.assessmentId ? (
        <AssessmentReview assessmentId={state.assessmentId} />
      ) : state.kind === "schedule" && state.application ? (
        <ScheduleForm application={state.application} />
      ) : state.kind === "feedback" && state.application ? (
        <FeedbackForm application={state.application} />
      ) : state.kind === "compare" ? (
        <CompareCandidates ids={state.candidateIds ?? []} />
      ) : null}
    </Modal>
  );
}

function LoginForm() {
  const { config } = useApp();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  return (
    <FormShell
      submit="Sign in to workspace"
      success="You're signed in."
      onSubmit={async () => {
        const result = await post<{ access_token: string; user: User }>(
          "/auth/login",
          { email, password },
        );
        tokenStore.set(result.access_token);
      }}
    >
      <p className="form-intro">
        Sign in with your staff account to create jobs, review screening
        evidence, and move candidates forward.
      </p>
      <label>
        Email address
        <input
          type="email"
          autoComplete="username"
          required
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>
      <label>
        Password
        <input
          type="password"
          required
          autoComplete="current-password"
          placeholder="Your password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      <div className="form-notice">
        <ShieldCheck size={17} />
        <p>
          {config.auth_mode === "supabase"
            ? "Staff accounts are provisioned by your workspace administrator. Workspace access is granted by an administrator."
            : "Local development accounts are documented in the project README. Public visitors have read-only access."}
        </p>
      </div>
    </FormShell>
  );
}

function JobForm({ job }: { job?: Job }) {
  const { data } = useApp();
  const [managerIds, setManagerIds] = useState<string[]>(
    job?.manager_ids ?? [],
  );
  const [status, setStatus] = useState(job?.status ?? "open");
  const [title, setTitle] = useState(job?.title ?? "");
  const [department, setDepartment] = useState(
    job?.department ?? "Engineering",
  );
  const [location, setLocation] = useState(job?.location ?? "Remote");
  const [description, setDescription] = useState(job?.description ?? "");
  const [criteria, setCriteria] = useState<Criterion[]>(job?.criteria ?? []);
  const [confirmed, setConfirmed] = useState(job?.criteria_confirmed ?? false);
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState("");
  const weight = criteria.reduce((sum, c) => sum + Number(c.weight), 0);
  const change = (
    index: number,
    key: keyof Criterion,
    value: string | number,
  ) =>
    setCriteria((old) =>
      old.map((c, i) => (i === index ? { ...c, [key]: value } : c)),
    );
  async function draft() {
    setDrafting(true);
    setDraftError("");
    try {
      const result = await post<{ criteria: Criterion[] }>(
        "/jobs/draft-criteria",
        { description },
      );
      setCriteria(result.criteria);
      setConfirmed(false);
    } catch (e) {
      setDraftError((e as Error).message);
    } finally {
      setDrafting(false);
    }
  }
  return (
    <FormShell
      submit={job ? "Save job & rubric" : "Create job opening"}
      success={
        job
          ? "Job updated. Existing candidates require explicit rescreening when the rubric changes."
          : "Your job opening is ready for candidates."
      }
      onSubmit={async () => {
        if (!criteria.length)
          throw new Error("Add at least one screening criterion.");
        if (Math.abs(weight - 100) > 0.01)
          throw new Error("Criterion weights must add up to 100%.");
        if (criteria.some((c) => !c.label.trim() || c.weight <= 0))
          throw new Error(
            "Give every criterion a label and a positive weight.",
          );
        const body = {
          title,
          department,
          location,
          description,
          criteria,
          criteria_confirmed: confirmed,
          manager_ids: managerIds,
        };
        if (job) await patch(`/jobs/${job.id}`, { ...body, status });
        else await post("/jobs", body);
      }}
    >
      <div className="form-row">
        <label>
          Job title
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Python Backend Engineer"
            maxLength={150}
          />
        </label>
        <label>
          Department
          <input
            required
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
          />
        </label>
      </div>
      {job && (
        <label>
          Opening status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">Open</option>
            <option value="draft">Draft</option>
            <option value="closed">Closed</option>
          </select>
        </label>
      )}
      {(data.users ?? []).some(
        (user) => user.role === "manager" || user.role === "hiring_manager",
      ) && (
        <fieldset className="question-editor">
          <legend>Hiring manager access</legend>
          {(data.users ?? [])
            .filter(
              (user) =>
                user.role === "manager" || user.role === "hiring_manager",
            )
            .map((manager) => (
              <label className="checkbox-label" key={manager.id}>
                <input
                  type="checkbox"
                  checked={managerIds.includes(manager.id)}
                  onChange={(e) =>
                    setManagerIds((old) =>
                      e.target.checked
                        ? [...old, manager.id]
                        : old.filter((id) => id !== manager.id),
                    )
                  }
                />
                <span>{manager.name}</span>
              </label>
            ))}
        </fieldset>
      )}
      <label>
        Location
        <input
          required
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="Remote, Bengaluru, or hybrid"
        />
      </label>
      <label>
        Job description
        <textarea
          required
          rows={5}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Describe the role, responsibilities, and skills that matter…"
          maxLength={20000}
        />
      </label>
      <div className="form-section-heading">
        <div>
          <h3>Your screening rubric</h3>
          <p>Clear criteria make consistent, explainable reviews.</p>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={drafting || description.trim().length < 20}
          onClick={() => void draft()}
        >
          {drafting ? (
            <Loader2 size={14} className="spin" />
          ) : (
            <Sparkles size={14} />
          )}
          Draft criteria
        </Button>
      </div>
      {draftError && (
        <p className="inline-error" role="alert">
          {draftError}
        </p>
      )}
      <div className="criteria-editor">
        {criteria.map((criterion, i) => (
          <div key={criterion.id} className="criterion-editor-row">
            <label className="sr-only" htmlFor={`criterion-${i}`}>
              Criterion {i + 1}
            </label>
            <input
              id={`criterion-${i}`}
              required
              value={criterion.label}
              onChange={(e) => change(i, "label", e.target.value)}
              placeholder="Job-relevant skill or experience"
            />
            <label className="weight-field">
              <input
                type="number"
                aria-label={`Criterion ${i + 1} weight`}
                required
                min="0.01"
                max="100"
                step="0.01"
                value={criterion.weight}
                onChange={(e) => change(i, "weight", Number(e.target.value))}
              />
              <span>%</span>
            </label>
            <button
              type="button"
              className="icon-button"
              aria-label={`Remove criterion ${i + 1}`}
              onClick={() =>
                setCriteria((old) => old.filter((_, k) => k !== i))
              }
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>
      <div className="criteria-editor-bottom">
        <Button
          type="button"
          variant="ghost"
          onClick={() =>
            setCriteria((old) => [
              ...old,
              {
                id: crypto.randomUUID(),
                label: "",
                weight: Math.max(100 - weight, 1),
              },
            ])
          }
        >
          <Plus size={14} />
          Add criterion
        </Button>
        <span className={weight === 100 ? "weight-valid" : "weight-invalid"}>
          Total weight: {weight}% / 100%
        </span>
      </div>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        <span>
          <strong>I’ve reviewed and approve these criteria.</strong>
          <small>
            Screening is available only after the rubric is confirmed.
          </small>
        </span>
      </label>
      {job && (
        <div className="form-notice">
          <FileText size={16} />
          <p>
            Changing this rubric creates a new version. Existing screening
            results remain visible and will be marked for rescreening.
          </p>
        </div>
      )}
    </FormShell>
  );
}

function UploadForm({ job }: { job?: Job }) {
  const { data } = useApp();
  const [jobId, setJobId] = useState(job?.id ?? data.jobs[0]?.id ?? "");
  const [files, setFiles] = useState<File[]>([]);
  const [synthetic, setSynthetic] = useState(false);
  return (
    <FormShell
      submit={`Import ${files.length || ""} ${files.length === 1 ? "resume" : "resumes"}`}
      success="Resumes queued for processing. Candidate profiles will update automatically."
      disabled={!jobId || !files.length || !synthetic}
      onSubmit={async () => {
        if (files.length > 10)
          throw new Error("Import at most ten resumes in a batch.");
        if (files.some((f) => f.size > 5 * 1024 * 1024))
          throw new Error("Each resume must be no larger than 5 MB.");
        const form = new FormData();
        files.forEach((file) => form.append("files", file));
        form.append("synthetic_confirmed", "true");
        await api(`/jobs/${jobId}/uploads`, { method: "POST", body: form });
      }}
    >
      <p className="form-intro">
        Bring in a small batch of fictional candidates. We’ll extract their
        profiles and preserve the source text for evidence-based screening.
      </p>
      <label>
        Job opening
        <select
          required
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
        >
          {data.jobs.map((j) => (
            <option key={j.id} value={j.id}>
              {j.title}
            </option>
          ))}
        </select>
      </label>
      <label className="upload-dropzone">
        <span className="upload-icon">
          <Upload size={25} />
        </span>
        <strong>Choose resumes to import</strong>
        <span>Text-based PDF or DOCX · Up to 10 files · 5 MB each</span>
        <input
          type="file"
          required
          multiple
          accept=".pdf,.docx"
          aria-label="Resume files"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
      </label>
      {files.length > 0 && (
        <ul className="selected-files">
          {files.map((file, i) => (
            <li key={`${file.name}-${i}`}>
              <FileText size={15} />
              <span>{file.name}</span>
              <small>{Math.ceil(file.size / 1024)} KB</small>
            </li>
          ))}
        </ul>
      )}
      <label className="checkbox-label">
        <input
          type="checkbox"
          required
          checked={synthetic}
          onChange={(e) => setSynthetic(e.target.checked)}
        />
        <span>
          <strong>
            These resumes contain fictional, synthetic information.
          </strong>
          <small>
            Do not upload real personal or confidential data to this portfolio
            demo.
          </small>
        </span>
      </label>
      <div className="form-notice">
        <FileText size={16} />
        <p>
          Scanned documents cannot be read in this version. Export a text-based
          PDF or DOCX instead.
        </p>
      </div>
    </FormShell>
  );
}

function ProfileForm({ candidate }: { candidate: Candidate }) {
  const [profile, setProfile] = useState({
    name: candidate.name,
    email: candidate.email ?? "",
    headline: candidate.headline,
    location: candidate.location ?? "",
    experience_years: candidate.experience_years ?? "",
    notice_period_days: candidate.notice_period_days ?? "",
    salary_expectation: candidate.salary_expectation?.toString() ?? "",
  });
  const [correctSource, setCorrectSource] = useState(false);
  const [resumeText, setResumeText] = useState("");
  const [skills, setSkills] = useState(candidate.skills.join(", "));
  const change = (key: string, value: string | number) =>
    setProfile((old) => ({ ...old, [key]: value }));
  return (
    <FormShell
      submit="Save profile corrections"
      success="Profile updated. Rescreen to evaluate the new profile version."
      onSubmit={async () => {
        await patch(`/candidates/${candidate.id}`, {
          ...profile,
          ...(correctSource ? { resume_text: resumeText } : {}),
          experience_years:
            profile.experience_years === ""
              ? null
              : Number(profile.experience_years),
          notice_period_days:
            profile.notice_period_days === ""
              ? null
              : Number(profile.notice_period_days),
          skills: skills
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        });
      }}
    >
      <div className="form-row">
        <label>
          Full name
          <input
            required
            value={profile.name}
            onChange={(e) => change("name", e.target.value)}
          />
        </label>
        <label>
          Email
          <input
            type="email"
            value={profile.email}
            onChange={(e) => change("email", e.target.value)}
          />
        </label>
      </div>
      <label>
        Headline
        <input
          value={profile.headline}
          onChange={(e) => change("headline", e.target.value)}
        />
      </label>
      <label>
        Skills, separated by commas
        <input value={skills} onChange={(e) => setSkills(e.target.value)} />
      </label>
      <div className="form-row">
        <label>
          Location
          <input
            value={profile.location}
            onChange={(e) => change("location", e.target.value)}
          />
        </label>
        <label>
          Experience in years
          <input
            type="number"
            min="0"
            max="60"
            step="0.5"
            value={profile.experience_years}
            onChange={(e) =>
              change(
                "experience_years",
                e.target.value === "" ? "" : Number(e.target.value),
              )
            }
          />
        </label>
      </div>
      <div className="form-row">
        <label>
          Notice period in days
          <input
            type="number"
            min="0"
            max="365"
            value={profile.notice_period_days}
            onChange={(e) =>
              change(
                "notice_period_days",
                e.target.value === "" ? "" : Number(e.target.value),
              )
            }
          />
        </label>
        <label>
          Salary expectation
          <input
            value={profile.salary_expectation}
            onChange={(e) => change("salary_expectation", e.target.value)}
          />
        </label>
      </div>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={correctSource}
          onChange={(e) => setCorrectSource(e.target.checked)}
        />
        <span>
          Replace the extracted resume text with a verified correction.
        </span>
      </label>
      {correctSource && (
        <label>
          Corrected resume text
          <textarea
            required
            minLength={10}
            maxLength={100000}
            rows={8}
            value={resumeText}
            onChange={(e) => setResumeText(e.target.value)}
            placeholder="Paste the complete corrected text from the synthetic resume."
          />
          <small>
            Future screening will cite this text. The original document remains
            available for download.
          </small>
        </label>
      )}
      <p className="small muted">
        Profile corrections create a new version. Original resume evidence is
        retained, and past results are preserved.
      </p>
    </FormShell>
  );
}

function StageForm({ application }: { application: Application }) {
  const { data } = useApp();
  const [stage, setStage] = useState(application.stage);
  const [note, setNote] = useState("");
  const candidate = getCandidate(data, application);
  return (
    <FormShell
      submit="Confirm stage change"
      success="Application stage updated and recorded in the audit history."
      onSubmit={async () => {
        await patch(`/applications/${application.id}/stage`, { stage, note });
      }}
    >
      <p className="form-intro">
        Choose the next step for <strong>{candidate?.name}</strong>. Hiring
        decisions are always made by a person.
      </p>
      <label>
        Application stage
        <select
          required
          value={stage}
          onChange={(e) => setStage(e.target.value)}
        >
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {label(s)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Decision note{" "}
        {["hired", "rejected", "withdrawn"].includes(stage)
          ? "(required)"
          : "(optional)"}
        <textarea
          rows={4}
          required={["hired", "rejected", "withdrawn"].includes(stage)}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Document the job-relevant reason for this decision…"
        />
      </label>
      <div className="form-notice">
        <ShieldCheck size={17} />
        <p>
          This action records a pipeline decision. It does not automatically
          email the candidate.
        </p>
      </div>
    </FormShell>
  );
}

function ScreeningReview({ screeningId }: { screeningId: string }) {
  const [approved, setApproved] = useState(true);
  const [notes, setNotes] = useState("");
  return (
    <FormShell
      submit={
        approved
          ? "Approve screening review"
          : "Return screening for correction"
      }
      success="Your screening review has been queued and recorded."
      onSubmit={async () => {
        await post(`/screenings/${screeningId}/review`, { approved, notes });
      }}
    >
      <p className="form-intro">
        Review the source-linked evidence before approving the screening result.
        Approval records your review; it does not change the candidate’s stage.
      </p>
      <label>
        Review outcome
        <select
          value={approved ? "approve" : "return"}
          onChange={(e) => setApproved(e.target.value === "approve")}
        >
          <option value="approve">Evidence checked — approve result</option>
          <option value="return">Needs correction — return result</option>
        </select>
      </label>
      <label>
        Review notes
        <textarea
          required={!approved}
          rows={4}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Add context, concerns, or information to clarify…"
        />
      </label>
    </FormShell>
  );
}

const defaultQuestions: Question[] = [
  {
    id: "q1",
    kind: "mcq",
    prompt: "Which practice best protects an API against SQL injection?",
    options: [
      "Parameterized queries",
      "Hiding the endpoint URL",
      "Client-side validation only",
    ],
    answer: "Parameterized queries",
    rubric: "Recognizes safe parameter binding.",
  },
  {
    id: "q2",
    kind: "mcq",
    prompt: "What is the main purpose of a database transaction?",
    options: [
      "To make related operations atomic",
      "To replace all database indexes",
      "To bypass validation",
    ],
    answer: "To make related operations atomic",
    rubric: "Understands atomic consistency.",
  },
  {
    id: "q3",
    kind: "short",
    prompt:
      "Describe a technical problem you solved. What tradeoffs did you consider, and how did you verify the result?",
    options: [],
    rubric:
      "Look for a clear problem, concrete contribution, tradeoff reasoning, and verification. Do not infer personality.",
  },
];
function AssessmentForm({ application }: { application: Application }) {
  const { data, notify } = useApp();
  const [questions, setQuestions] = useState<Question[]>(
    defaultQuestions.map((q) => ({ ...q, options: [...q.options] })),
  );
  const [sendEmail, setSendEmail] = useState(false);
  const [approved, setApproved] = useState(false);
  const [invite, setInvite] = useState("");
  const candidate = getCandidate(data, application);
  function edit(index: number, changes: Partial<Question>) {
    setQuestions((old) =>
      old.map((q, i) => (i === index ? { ...q, ...changes } : q)),
    );
  }
  if (invite)
    return (
      <div className="invitation-result">
        <span className="success-mark">
          <CheckCircle2 size={35} />
        </span>
        <h3>Assessment invitation ready</h3>
        <p>
          The invite for {candidate?.name} is ready. Copy it now; the token is
          shown only once and expires after seven days.
        </p>
        <label>
          Candidate invitation link
          <input readOnly value={invite} onFocus={(e) => e.target.select()} />
        </label>
        <div>
          <Button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(invite);
                notify("Invitation link copied.");
              } catch {
                notify(
                  "Select and copy the link above. Clipboard access is unavailable.",
                  true,
                );
              }
            }}
          >
            <Copy size={15} />
            Copy invitation
          </Button>
          <a
            className="button button-secondary"
            href={invite}
            target="_blank"
            rel="noreferrer"
          >
            Open candidate form
            <ExternalLink size={14} />
          </a>
        </div>
        <p className="small muted">
          The candidate can submit this assessment only once.
        </p>
      </div>
    );
  return (
    <FormShell
      submit="Approve & create invitation"
      closeAfter={false}
      success="Assessment created. Save the invitation link before closing."
      disabled={!approved}
      onSubmit={async () => {
        if (!questions.length) throw new Error("Add at least one question.");
        if (
          questions.some(
            (q) =>
              q.kind === "mcq" &&
              (!q.options.includes(q.answer ?? "") || q.options.length < 2),
          )
        )
          throw new Error(
            "Each MCQ needs at least two options and a correct answer.",
          );
        const result = await post<{ invite_url: string }>(
          `/applications/${application.id}/assessment`,
          { questions, send_email: sendEmail },
        );
        setInvite(result.invite_url);
      }}
    >
      <p className="form-intro">
        Prepare a short, job-relevant questionnaire for{" "}
        <strong>{candidate?.name}</strong>. Edit the example questions to fit
        this role before approving.
      </p>
      <div className="question-editor-list">
        {questions.map((question, i) => (
          <fieldset className="question-editor" key={question.id}>
            <legend>Question {i + 1}</legend>
            <div className="question-editor-toolbar">
              <select
                aria-label={`Question ${i + 1} type`}
                value={question.kind}
                onChange={(e) =>
                  edit(i, {
                    kind: e.target.value as "mcq" | "short",
                    answer: "",
                    options:
                      e.target.value === "mcq" ? ["Option 1", "Option 2"] : [],
                  })
                }
              >
                <option value="mcq">Multiple choice</option>
                <option value="short">Short answer</option>
              </select>
              <button
                className="icon-button"
                type="button"
                aria-label={`Remove question ${i + 1}`}
                onClick={() =>
                  setQuestions((old) => old.filter((_, index) => index !== i))
                }
              >
                <Trash2 size={15} />
              </button>
            </div>
            <label>
              Question
              <textarea
                required
                rows={2}
                value={question.prompt}
                onChange={(e) => edit(i, { prompt: e.target.value })}
              />
            </label>
            {question.kind === "mcq" && (
              <>
                <label>
                  Options, one per line
                  <textarea
                    required
                    rows={3}
                    value={question.options.join("\n")}
                    onChange={(e) =>
                      edit(i, { options: e.target.value.split("\n") })
                    }
                  />
                </label>
                <label>
                  Correct answer
                  <select
                    required
                    value={question.answer ?? ""}
                    onChange={(e) => edit(i, { answer: e.target.value })}
                  >
                    <option value="">Select the correct option</option>
                    {question.options.filter(Boolean).map((option, k) => (
                      <option key={k} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            <label>
              {question.kind === "short"
                ? "Review rubric"
                : "Answer explanation"}
              <textarea
                rows={2}
                value={question.rubric ?? ""}
                onChange={(e) => edit(i, { rubric: e.target.value })}
              />
            </label>
          </fieldset>
        ))}
      </div>
      <Button
        type="button"
        variant="secondary"
        onClick={() =>
          setQuestions((old) => [
            ...old,
            {
              id: crypto.randomUUID(),
              kind: "short",
              prompt: "",
              options: [],
              rubric: "",
            },
          ])
        }
      >
        <Plus size={14} />
        Add question
      </Button>
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={sendEmail}
          onChange={(e) => setSendEmail(e.target.checked)}
        />
        <span>
          <strong>Send an approved test email with this invitation.</strong>
          <small>
            Live email is restricted to your configured test inbox. Preview mode
            records a draft.
          </small>
        </span>
      </label>
      <label className="checkbox-label">
        <input
          type="checkbox"
          required
          checked={approved}
          onChange={(e) => setApproved(e.target.checked)}
        />
        <span>
          <strong>I approve these questions and scoring criteria.</strong>
          <small>
            MCQ scores stay separate from resume screening. Short answers need
            human review.
          </small>
        </span>
      </label>
    </FormShell>
  );
}

function ReinviteForm({ assessmentId }: { assessmentId: string }) {
  const { notify } = useApp();
  const [invite, setInvite] = useState("");
  if (invite)
    return (
      <div className="invitation-result">
        <span className="success-mark">
          <CheckCircle2 size={35} />
        </span>
        <h3>The new invitation is ready</h3>
        <p>
          Copy this link now. It expires after seven days and replaces the
          previous invitation.
        </p>
        <label>
          Candidate invitation link
          <input readOnly value={invite} onFocus={(e) => e.target.select()} />
        </label>
        <div>
          <Button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(invite);
                notify("New invitation copied.");
              } catch {
                notify("Select and copy the link above.", true);
              }
            }}
          >
            <Copy size={15} />
            Copy invitation
          </Button>
          <a
            className="button button-secondary"
            href={invite}
            target="_blank"
            rel="noreferrer"
          >
            Open candidate form
            <ExternalLink size={14} />
          </a>
        </div>
      </div>
    );
  return (
    <FormShell
      submit="Generate a new invitation"
      closeAfter={false}
      success="A new seven-day invitation has been generated."
      onSubmit={async () => {
        const result = await post<{ invite_url: string }>(
          `/assessments/${assessmentId}/reinvite`,
          { send_email: false },
        );
        setInvite(result.invite_url);
      }}
    >
      <p className="form-intro">
        Generate a new access link for this assessment if the original was lost
        or expired.
      </p>
      <div className="form-notice">
        <ShieldCheck size={17} />
        <p>
          The old invitation will stop working immediately. Candidate questions
          remain unchanged. Copy the replacement link before closing this
          dialog.
        </p>
      </div>
      <label className="checkbox-label">
        <input type="checkbox" required />
        <span>I approve replacing the existing invitation.</span>
      </label>
    </FormShell>
  );
}

function AssessmentReview({ assessmentId }: { assessmentId: string }) {
  const [notes, setNotes] = useState("");
  return (
    <FormShell
      submit="Record assessment review"
      success="Assessment review saved."
      onSubmit={async () => {
        await post(`/assessments/${assessmentId}/review`, { notes });
      }}
    >
      <p className="form-intro">
        Review the candidate’s responses against the approved rubric. AI
        feedback is advisory and cannot make a hiring decision.
      </p>
      <label>
        Reviewer notes
        <textarea
          required
          rows={5}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Record the evidence and job-relevant observations that informed your review…"
        />
      </label>
      <label className="checkbox-label">
        <input type="checkbox" required />
        <span>
          I have reviewed the candidate responses and any AI feedback.
        </span>
      </label>
    </FormShell>
  );
}

function toLocalInput(value: string) {
  const d = new Date(value);
  if (!Number.isFinite(d.getTime())) return "";
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
function ScheduleForm({ application }: { application: Application }) {
  const { data } = useApp();
  const availability = data.assessments
    .filter((a) => a.application_id === application.id)
    .flatMap((a) => a.availability ?? []);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(10, 0, 0, 0);
  const [availabilityMessage, setAvailabilityMessage] = useState("");
  const [checking, setChecking] = useState(false);
  const [start, setStart] = useState(
    toLocalInput(availability[0]?.start ?? tomorrow.toISOString()),
  );
  const [end, setEnd] = useState(
    toLocalInput(
      availability[0]?.end ??
        new Date(tomorrow.getTime() + 3600000).toISOString(),
    ),
  );
  const [approved, setApproved] = useState(false);
  return (
    <FormShell
      submit="Confirm interview booking"
      success="Interview booking queued. Calendar availability will be checked before creation."
      disabled={!approved}
      onSubmit={async () => {
        const s = new Date(start);
        const e = new Date(end);
        if (s <= new Date())
          throw new Error("Choose an interview time in the future.");
        if (e <= s)
          throw new Error("The end time must be after the start time.");
        await post(`/applications/${application.id}/interviews`, {
          start: s.toISOString(),
          end: e.toISOString(),
          timezone: zone,
        });
      }}
    >
      <p className="form-intro">
        Schedule an interview with{" "}
        <strong>{getCandidate(data, application)?.name}</strong>. Times below
        use your device timezone: <strong>{zone}</strong>.
      </p>
      {availability.length > 0 && (
        <div className="candidate-slot-list">
          <span className="small-label">CANDIDATE AVAILABILITY</span>
          {availability.map((slot, i) => (
            <button
              type="button"
              key={i}
              onClick={() => {
                setStart(toLocalInput(slot.start));
                setEnd(toLocalInput(slot.end));
                setAvailabilityMessage("");
              }}
            >
              <CheckCircle2 size={15} />
              {date(slot.start, true)} · your device time
              <ArrowRight size={14} />
            </button>
          ))}
        </div>
      )}
      <div className="form-row">
        <label>
          Interview start
          <input
            type="datetime-local"
            required
            value={start}
            onChange={(e) => {
              setStart(e.target.value);
              setAvailabilityMessage("");
            }}
          />
        </label>
        <label>
          Interview end
          <input
            type="datetime-local"
            required
            value={end}
            onChange={(e) => {
              setEnd(e.target.value);
              setAvailabilityMessage("");
            }}
          />
        </label>
      </div>
      <div className="check-availability">
        <Button
          type="button"
          variant="secondary"
          disabled={checking}
          onClick={async () => {
            setChecking(true);
            setAvailabilityMessage("");
            try {
              const from = new Date(start);
              const until = new Date(end);
              if (
                !Number.isFinite(from.getTime()) ||
                !Number.isFinite(until.getTime()) ||
                until <= from
              )
                throw new Error("Enter a valid start and end time first.");
              const query = new URLSearchParams({
                start: from.toISOString(),
                end: until.toISOString(),
              });
              const result = await api<{
                busy: unknown[];
                status?: string;
              }>(`/integrations/calendar/freebusy?${query}`);
              setAvailabilityMessage(
                result.status === "preview"
                  ? "Preview mode. Connect Google Calendar and enable live integrations to check actual availability."
                  : result.busy.length
                    ? "This window includes a calendar conflict. Choose another time."
                    : "The selected calendar window is available. Availability is rechecked when booking.",
              );
            } catch (error) {
              setAvailabilityMessage((error as Error).message);
            } finally {
              setChecking(false);
            }
          }}
        >
          {checking ? "Checking…" : "Check calendar availability"}
        </Button>
        {availabilityMessage && (
          <p className="small" role="status">
            {availabilityMessage}
          </p>
        )}
      </div>
      <div className="form-notice">
        <ShieldCheck size={17} />
        <p>
          Calendar conflicts are checked again before booking. Invitations can
          only include configured owned test accounts. Preview mode does not
          create an external event.
        </p>
      </div>
      <label className="checkbox-label">
        <input
          type="checkbox"
          required
          checked={approved}
          onChange={(e) => setApproved(e.target.checked)}
        />
        <span>
          I approve this interview and any test-calendar notifications.
        </span>
      </label>
    </FormShell>
  );
}

function FeedbackForm({ application }: { application: Application }) {
  const [rating, setRating] = useState(3);
  const [notes, setNotes] = useState("");
  return (
    <FormShell
      submit="Save team feedback"
      success="Your feedback has been added to the candidate profile."
      onSubmit={async () => {
        await post(`/applications/${application.id}/feedback`, {
          rating,
          notes,
        });
      }}
    >
      <p className="form-intro">
        Keep feedback specific and job-relevant. Describe what you observed and
        which criteria it supports.
      </p>
      <label>
        Assessment of job-relevant evidence
        <select
          value={rating}
          onChange={(e) => setRating(Number(e.target.value))}
        >
          <option value="1">1 — Significant gaps</option>
          <option value="2">2 — Some gaps</option>
          <option value="3">3 — Meets expectations</option>
          <option value="4">4 — Strong evidence</option>
          <option value="5">5 — Exceptional evidence</option>
        </select>
      </label>
      <label>
        Your observations
        <textarea
          required
          minLength={5}
          rows={5}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Share concrete examples, strengths, and open questions…"
        />
      </label>
    </FormShell>
  );
}

function CompareCandidates({ ids }: { ids: string[] }) {
  const { data, select, close } = useApp();
  const applications = ids
    .map((id) => data.applications.find((a) => a.id === id))
    .filter((a): a is Application => !!a);
  return (
    <div className="compare-content">
      <p className="form-intro">
        Compare evidence against each candidate’s job rubric. Scores from
        different roles are not directly comparable.
      </p>
      <div
        className="compare-grid"
        style={{
          gridTemplateColumns: `repeat(${Math.max(applications.length, 1)}, minmax(200px, 1fr))`,
        }}
      >
        {applications.map((application, index) => {
          const candidate = getCandidate(data, application);
          const screening = latestScreening(data, application.id);
          return (
            <section className="compare-column" key={application.id}>
              <Avatar
                name={candidate?.name ?? "Candidate"}
                index={index}
                size="avatar-large"
              />
              <h3>{candidate?.name}</h3>
              <p>{getJob(data, application)?.title}</p>
              <Score
                score={screeningScore(screening)}
                emptyLabel={screening ? label(screening.status) : undefined}
              />
              <span className="small muted">Evidence match</span>
              <div className="compare-skills">
                {candidate?.skills?.map((skill) => (
                  <span key={skill}>{skill}</span>
                ))}
              </div>
              <div className="compare-criteria">
                {screening?.matches.map((match) => (
                  <div key={match.criterion_id}>
                    <strong>{match.label}</strong>
                    <Badge
                      tone={
                        match.status === "supported"
                          ? "green"
                          : match.status === "partial"
                            ? "amber"
                            : "neutral"
                      }
                    >
                      {match.status === "insufficient"
                        ? "Needs evidence"
                        : label(match.status)}
                    </Badge>
                    <p>{match.reason}</p>
                  </div>
                ))}
              </div>
              <Button
                variant="secondary"
                onClick={() => {
                  close();
                  select(application);
                }}
              >
                View full profile
                <ArrowRight size={14} />
              </Button>
            </section>
          );
        })}
      </div>
      <div className="detail-policy">
        <ShieldCheck size={14} />
        The same job rubric supports consistent comparison. Hiring decisions
        remain yours.
      </div>
    </div>
  );
}
