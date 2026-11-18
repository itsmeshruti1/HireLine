export type Role = "admin" | "recruiter" | "manager" | "hiring_manager";
export type User = { id: string; name: string; email: string; role: Role };
export type Criterion = { id: string; label: string; weight: number };
export type Job = {
  id: string;
  title: string;
  description: string;
  department: string;
  location: string;
  status: string;
  criteria: Criterion[];
  criteria_version: number;
  criteria_confirmed: boolean;
  manager_ids?: string[];
  created_at: string;
};
export type Candidate = {
  id: string;
  name: string;
  email?: string;
  headline: string;
  skills: string[];
  experience_years?: number;
  location?: string;
  notice_period_days?: number;
  salary_expectation?: string | number;
  profile_version: number;
  documents?: {
    id: string;
    filename: string;
    status: string;
    error?: string;
  }[];
};
export type Application = {
  id: string;
  job_id: string;
  candidate_id: string;
  stage: string;
  created_at: string;
  updated_at: string;
};
export type Evidence = { segment_id: string; quote: string };
export type Match = {
  criterion_id: string;
  label: string;
  weight: number;
  status: string;
  reason: string;
  evidence: Evidence[];
};
export type Screening = {
  id: string;
  application_id: string;
  score: number;
  status: string;
  criteria_version: number;
  profile_version: number;
  matches: Match[];
  missing_count: number;
  reviewed_at?: string;
  review_notes?: string;
  engine?: "demo" | "gemini" | "unknown";
  model?: string;
  created_at?: string;
};
export type Question = {
  id: string;
  kind: "mcq" | "short";
  prompt: string;
  options: string[];
  answer?: string;
  rubric?: string;
};
export type Availability = { start: string; end: string; timezone: string };
export type Assessment = {
  id: string;
  application_id: string;
  status: string;
  questions: Question[];
  answers?: Record<string, string>;
  availability?: Availability[];
  score?: number;
  mcq_score?: number;
  ai_feedback?: unknown;
  short_answer_feedback?: { question_id: string; feedback: string }[];
  review_notes?: string;
  submitted_at?: string;
  reviewed_at?: string;
};
export type Interview = {
  id: string;
  application_id: string;
  start: string;
  end: string;
  timezone: string;
  status: string;
  meeting_url?: string;
  event_url?: string;
};
export type Feedback = {
  id: string;
  application_id: string;
  notes: string;
  rating: number;
  created_at?: string;
  author_name?: string;
};
export type Activity = {
  id?: string;
  action?: string;
  message?: string;
  entity_type?: string;
  created_at?: string;
  actor_name?: string;
};
export type Task = {
  id: string;
  kind: string;
  status: string;
  error?: string;
  attempts?: number;
  updated_at?: string;
  created_at?: string;
};
export type Workspace = {
  jobs: Job[];
  candidates: Candidate[];
  applications: Application[];
  screenings: Screening[];
  assessments: Assessment[];
  interviews: Interview[];
  feedback: Feedback[];
  activities: Activity[];
  tasks: Task[];
  metrics: Record<string, unknown>;
  users?: User[];
};
export type Config = {
  auth_mode?: string;
  ai_mode?: string;
  environment?: string;
  app_env?: string;
  synthetic_only?: boolean;
  [key: string]: unknown;
};
export type IntegrationStatus = {
  name?: string;
  configured?: boolean;
  connected?: boolean;
  mode?: string;
  status?: string;
  message?: string;
  [key: string]: unknown;
};
export type Integrations = Record<
  string,
  IntegrationStatus | string | boolean | unknown
>;
