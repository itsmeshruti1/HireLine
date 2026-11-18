import { createContext, useContext } from "react";
import type {
  Application,
  Candidate,
  Config,
  Job,
  Screening,
  User,
  Workspace,
} from "./types";

export type Page =
  "overview" | "jobs" | "candidates" | "pipeline" | "analytics" | "settings";
export type ModalState = {
  kind:
    | "login"
    | "job"
    | "upload"
    | "profile"
    | "stage"
    | "assessment"
    | "reinvite"
    | "schedule"
    | "feedback"
    | "review"
    | "assessment-review"
    | "compare";
  job?: Job;
  candidate?: Candidate;
  application?: Application;
  screeningId?: string;
  assessmentId?: string;
  candidateIds?: string[];
} | null;
export type AppContext = {
  data: Workspace;
  user: User | null;
  config: Config;
  busy: boolean;
  refresh: () => Promise<void>;
  open: (modal: ModalState) => void;
  close: () => void;
  notify: (message: string, error?: boolean) => void;
  navigate: (page: Page, jobId?: string) => void;
  select: (application: Application | null) => void;
  command: (action: () => Promise<unknown>, success: string) => Promise<void>;
};
export const Context = createContext<AppContext | null>(null);
export function useApp() {
  const context = useContext(Context);
  if (!context) throw new Error("Workspace context missing");
  return context;
}
export function canManage(user: User | null) {
  return !!user && (user.role === "admin" || user.role === "recruiter");
}
export function latestScreening(data: Workspace, applicationId: string) {
  return data.screenings
    .filter((s) => s.application_id === applicationId)
    .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))[0];
}
export function screeningScore(screening: Screening | undefined) {
  if (
    !screening ||
    !["approved", "awaiting_review", "reviewing", "rejected"].includes(
      screening.status,
    )
  )
    return undefined;
  return screening.score;
}
export function getCandidate(data: Workspace, application: Application) {
  return data.candidates.find((c) => c.id === application.candidate_id);
}
export function getJob(data: Workspace, application: Application) {
  return data.jobs.find((j) => j.id === application.job_id);
}
export const STAGES = [
  "new",
  "screening",
  "shortlisted",
  "assessment",
  "interview",
  "hired",
  "rejected",
  "withdrawn",
];
