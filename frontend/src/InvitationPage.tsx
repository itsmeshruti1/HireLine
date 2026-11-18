import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowRight,
  CalendarDays,
  CheckCircle2,
  Clock3,
  FileCheck2,
  Loader2,
  Plus,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { api, post } from "./api";
import type { Question } from "./types";
import { Badge, Button, date, Spinner } from "./ui";

type Invitation = {
  submitted: boolean;
  status?: string;
  job_title: string;
  expires_at?: string;
  questions?: Question[];
};
type Slot = { start: string; end: string };
export function InvitationPage({ token }: { token: string }) {
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [slots, setSlots] = useState<Slot[]>([]);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  useEffect(() => {
    api<Invitation>(`/invitations/${encodeURIComponent(token)}`)
      .then(setInvitation)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [token]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const availability = slots.map((slot) => {
        const start = new Date(slot.start);
        const end = new Date(slot.end);
        if (
          !Number.isFinite(start.getTime()) ||
          !Number.isFinite(end.getTime()) ||
          start <= new Date() ||
          end <= start
        )
          throw new Error(
            "Each availability window must start in the future and end after its start.",
          );
        if (end.getTime() - start.getTime() > 8 * 3600000)
          throw new Error(
            "Please keep each availability window to eight hours or less.",
          );
        return { start: start.toISOString(), end: end.toISOString(), timezone };
      });
      await post(`/invitations/${encodeURIComponent(token)}`, {
        answers,
        availability,
      });
      setInvitation((old) => (old ? { ...old, submitted: true } : old));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="candidate-portal">
      <header className="portal-header">
        <a className="brand brand-light" href="/">
          <span className="brand-mark">
            h<span />
          </span>
          <span>
            hireline<span className="brand-period">.</span>
          </span>
        </a>
        <span>
          <ShieldCheck size={15} />
          Private candidate assessment
        </span>
      </header>
      <main className="portal-main">
        {loading ? (
          <Spinner text="Opening your invitation…" />
        ) : invitation?.submitted ? (
          <section className="portal-success">
            <span className="portal-success-icon">
              <CheckCircle2 size={43} />
            </span>
            <Badge tone="green">Responses recorded</Badge>
            <h1>
              Your responses
              <br />
              are recorded<span>.</span>
            </h1>
            <p>
              Your responses{slots.length ? " and availability" : ""} for{" "}
              <strong>{invitation.job_title}</strong> have been recorded. The
              recruiting team will review your submission.
            </p>
            <div>
              <FileCheck2 size={18} />
              <span>
                This assessment has been submitted. No further changes can be
                made with this invitation.
              </span>
            </div>
            <p className="small muted">
              This is a synthetic portfolio demonstration, not a real hiring
              process.
            </p>
            <a className="text-link" href="/">
              Explore the workspace
              <ArrowRight size={15} />
            </a>
          </section>
        ) : !invitation ? (
          <section className="portal-error">
            <span className="empty-mark">
              <Clock3 size={26} />
            </span>
            <h1>
              Invitation unavailable<span>.</span>
            </h1>
            <p role="alert">{error || "This invitation is unavailable."}</p>
            <p className="small muted">
              Ask the recruiter for a new invitation. Links expire after seven
              days.
            </p>
            <a className="text-link" href="/">
              Back to Hireline
              <ArrowRight size={15} />
            </a>
          </section>
        ) : (
          <>
            <div className="portal-intro">
              <Badge tone="purple">CANDIDATE QUESTIONNAIRE</Badge>
              <h1>
                Your assessment<span>.</span>
              </h1>
              <p>Answer the questions below using concrete examples.</p>
              <div className="portal-job">
                <span className="portal-job-icon">
                  <FileCheck2 size={21} />
                </span>
                <div>
                  <strong>{invitation.job_title}</strong>
                  <span>
                    {invitation.questions?.length ?? 0} questions · Expires{" "}
                    {date(invitation.expires_at)}
                  </span>
                </div>
              </div>
            </div>
            <form onSubmit={submit}>
              <div className="portal-form-panel">
                {invitation.questions?.map((question, index) => (
                  <fieldset className="portal-question" key={question.id}>
                    <legend>
                      <span>QUESTION {String(index + 1).padStart(2, "0")}</span>
                      {question.prompt}
                    </legend>
                    {question.kind === "mcq" ? (
                      <div className="portal-options">
                        {question.options.map((option, k) => (
                          <label
                            className={
                              answers[question.id] === option
                                ? "portal-option-selected"
                                : ""
                            }
                            key={k}
                          >
                            <input
                              type="radio"
                              required
                              name={question.id}
                              value={option}
                              checked={answers[question.id] === option}
                              onChange={() =>
                                setAnswers((old) => ({
                                  ...old,
                                  [question.id]: option,
                                }))
                              }
                            />
                            <span>{option}</span>
                          </label>
                        ))}
                      </div>
                    ) : (
                      <textarea
                        aria-label={question.prompt}
                        required
                        rows={5}
                        maxLength={10000}
                        placeholder="Share a concrete example or explain your reasoning…"
                        value={answers[question.id] ?? ""}
                        onChange={(e) =>
                          setAnswers((old) => ({
                            ...old,
                            [question.id]: e.target.value,
                          }))
                        }
                      />
                    )}
                  </fieldset>
                ))}
              </div>
              <section className="portal-availability">
                <div className="form-section-heading">
                  <div>
                    <h2>Interview availability</h2>
                    <p>
                      Optionally share when you’re available for an interview.
                    </p>
                  </div>
                  <CalendarDays size={25} />
                </div>
                <p className="small muted">
                  Times use your device timezone: <strong>{timezone}</strong>.
                  Availability is a preference, not a confirmed booking.
                </p>
                {slots.map((slot, index) => (
                  <div className="availability-editor" key={index}>
                    <label>
                      Available from
                      <input
                        type="datetime-local"
                        required
                        value={slot.start}
                        onChange={(e) =>
                          setSlots((old) =>
                            old.map((s, i) =>
                              i === index ? { ...s, start: e.target.value } : s,
                            ),
                          )
                        }
                      />
                    </label>
                    <label>
                      Until
                      <input
                        type="datetime-local"
                        required
                        value={slot.end}
                        onChange={(e) =>
                          setSlots((old) =>
                            old.map((s, i) =>
                              i === index ? { ...s, end: e.target.value } : s,
                            ),
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={`Remove availability ${index + 1}`}
                      onClick={() =>
                        setSlots((old) => old.filter((_, i) => i !== index))
                      }
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="secondary"
                  disabled={slots.length >= 10}
                  onClick={() =>
                    setSlots((old) => [...old, { start: "", end: "" }])
                  }
                >
                  <Plus size={15} />
                  Add availability
                </Button>
              </section>
              <div className="portal-submit">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    required
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  <span>
                    I am submitting fictional demo responses and understand I
                    can submit this assessment only once.
                  </span>
                </label>
                {error && (
                  <p className="inline-error" role="alert">
                    {error}
                  </p>
                )}
                <Button type="submit" disabled={busy || !confirmed}>
                  {busy ? (
                    <Loader2 size={16} className="spin" />
                  ) : (
                    <CheckCircle2 size={16} />
                  )}
                  {busy ? "Submitting…" : "Submit my responses"}
                  <ArrowRight size={15} />
                </Button>
              </div>
            </form>
          </>
        )}
        <footer className="portal-footer">
          <span>
            <ShieldCheck size={14} />
            Private invitation · Fictional candidate data
          </span>
          <span>Powered by hireline.</span>
        </footer>
      </main>
    </div>
  );
}
