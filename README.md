# Hireline — Recruiter AI Workspace

An explainable recruiting portfolio application: create a job, inspect resume evidence,
review a screening, invite a candidate to an assessment, schedule an interview, and record
a decision. All included people, employers, and resumes are fictional.

[Watch the nine-minute narrated walkthrough](output/demo/hireline-end-to-end.mp4) ·
[Download captions](output/demo/hireline-demo.srt) · [Verification results](docs/verification.md)

## Run locally

Requires **Python 3.12**, **Node.js 22.12+**, and npm. No API keys are needed for the local demo.
From the repository root:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
cd frontend
npm.cmd ci
cd ..
.venv/Scripts/python.exe scripts/dev.py
```

On macOS/Linux, use `.venv/bin/python` in place of `.venv/Scripts/python.exe`, and `npm` in place of `npm.cmd`.
If uv is unavailable, create a Python 3.12 virtual environment with `python -m venv .venv`, then
use its `python -m pip install -r requirements.txt`.

Open **http://127.0.0.1:5173**. API documentation is at **http://127.0.0.1:8000/docs**.
The local database, private uploaded files, and workflow checkpoints live in ignored `data/`.
Ctrl+C stops both development servers. Launch from the repository root so fixture and environment paths resolve consistently.

The public view is read-only. Use **Staff sign in** for the local workspace:

| Email | Password | Role |
| --- | --- | --- |
| `admin@demo.local` | `local-demo-only` | Admin |
| `recruiter@demo.local` | `local-demo-only` | Recruiter |
| `manager@demo.local` | `local-demo-only` | Assigned hiring manager |

These credentials work only with local/test authentication. Production refuses that authentication mode.
Public signup is not implemented. Do not expose a local-mode backend to the public internet.

## Included workflow

- Jobs with recruiter-confirmed, weighted criteria and versioned edits.
- Up to ten synthetic PDF/DOCX resumes per upload, 5 MB per file.
- Editable profiles, separate candidates/applications, and evidence-based comparison.
- Persistent LangGraph screening pauses, explicit reviews, and stale-result detection.
- Manual pipeline changes and decision notes; scoring never changes a hiring stage.
- Editable MCQ/short-answer assessments, hashed seven-day invitations, single submission, and availability collection.
- Deterministic MCQ scores and separately reviewed advisory short-answer feedback.
- Interview availability checks, approved booking actions, feedback, and audit history.
- Pipeline counts, stage durations, processing failures, and recoverable task states.
- Read-only public fixtures isolated from private staff changes.

The default **demo matcher** uses deterministic term matching. It is labelled as such in the UI.
**Preview communication** stores a simulated action without sending email or creating a calendar event.
Neither mode silently pretends to call a provider. Live provider code is included but needs your accounts.

## Configure live test integrations

Copy `.env.example` to `.env` and keep it untracked. Restart the backend after changing settings.
Credentials never belong in `frontend/.env`, browser code, screenshots, or commits.

### Gemini

1. Create a Gemini API project/key with billing disabled.
2. Verify a currently available free-tier model supporting structured output in your account.
3. Set `GEMINI_API_KEY`, its exact `GEMINI_MODEL`, and `AI_MODE=gemini`.
4. Screen one sample resume before running larger batches.

Only fictional data is permitted. Unpaid Gemini terms restrict submission of personal/confidential
information. Quota exhaustion produces an error; there is no paid fallback. The provider model ID
is intentionally not guessed or set to an expiring preview alias.

### Resend

Set `RESEND_API_KEY`, `RESEND_TEST_INBOX` to your Resend signup email, and `EXTERNAL_MODE=live`.
All actual delivery is redirected to that inbox at the provider boundary. A paid domain is unnecessary
for this test path. Enable email when approving an assessment invitation. Check the action receipt;
ambiguous failures require provider-log reconciliation rather than blind resending.

### Google Calendar

1. Create a Google Cloud project, enable Calendar API, and configure a Web application OAuth client.
2. Keep the OAuth application in Testing and add only your owned accounts as test users.
3. Register the exact `GOOGLE_REDIRECT_URI`, defaulting to
   `http://127.0.0.1:8000/api/integrations/calendar/callback` locally.
4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and comma-separated `CALENDAR_ALLOWED_EMAILS`.
5. Set a stable `TOKEN_ENCRYPTION_KEY`, generated with:

   ```powershell
   .venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

6. Sign in as admin and connect Calendar in Settings. Use `EXTERNAL_MODE=live` for real test bookings.

Calendar notifications also go only to configured owned test accounts. Testing-mode refresh tokens
can expire after seven days; reconnect when prompted. Availability is checked immediately before
creation, but a third-party calendar change can still race with booking.

## Verification

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe scripts/evaluate.py
cd frontend
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

The backend tests isolate their databases and mock external providers. The optional PostgreSQL
test runs when `POSTGRES_TEST_URL` is supplied; CI includes a real PostgreSQL service.
Browser tests start their own application servers; see `frontend/playwright.config.ts` for ports.

The tracked [evaluation report](docs/evaluation.md) and JSON contain measured results from
the current fixture set, including the keyword baseline and limitations. Measure Gemini separately:

```powershell
.venv/Scripts/python.exe scripts/evaluate.py --mode gemini --confirm-synthetic
```

This consumes the selected account's free quota. Regenerate all twenty sample resumes with
`python scripts/generate_samples.py`. The labels are author-assigned, not independently validated.

## Deploy without a paid service

See [deployment instructions](docs/deployment.md). `render.yaml` defines a free API service and
static frontend; Supabase supplies the external database, authentication, and private file bucket.
`Dockerfile` starts one Uvicorn process and runs Alembic migrations before serving traffic.

Deployment requires your own Supabase and Render projects, provider credentials, and staff accounts.
They are not created or billed by local setup. Leave paid plans and automatic upgrades disabled.
Render Free can sleep/restart, and Supabase Free can pause after inactivity. Persistent queued work
resumes when the API wakes; timed reminders and guaranteed always-on processing are excluded.

## Repository guide

| Location | Purpose |
| --- | --- |
| `backend/app` | API, authorization, relational models, worker, and provider adapters |
| `backend/alembic` | Tracked schema migrations |
| `backend/tests` | API, persistence, source verification, and mocked provider checks |
| `frontend/src` | React dashboard and candidate forms |
| `fixtures` / `samples/resumes` | Three jobs, twenty fictional candidates, labels, and uploadable documents |
| `scripts` | Development launcher, evaluation, staff provisioning, and storage lockdown |
| `docs` | Architecture, deployment, evaluation, and demo walkthrough |

Background checks, scraping, public applications, coding execution, OCR, voice interviewing,
demographic inference, predictive hiring, and automatic candidate rejection are outside this release.
