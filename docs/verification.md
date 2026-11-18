# Release verification

Verified on 18 November 2026 on Windows with Python 3.12 and Microsoft Edge.

Publication check on 19 November: the production build passed after the wording review.
Ten browser tests passed on the first run; the public-demo test needed its banner selector
scoped to distinguish it from the sidebar label, then passed on rerun. No application
behavior changed in that follow-up. A scan of publishable files and Git history found no
matches for common credential formats or configured local secrets. `.env`, runtime data,
and local test artifacts remain excluded from Git.

| Check | Result |
| --- | --- |
| Backend/API/service/migration tests | 92 passed, zero skips, with PostgreSQL 16.15 available |
| PostgreSQL runtime | Durable checkpoint resume, concurrent requests, queue locks, provenance and time-zone handling passed |
| Playwright tests | 11 passed |
| Automated accessibility | Zero WCAG A/AA violations detected on six routes at 390 px and 1440 px, plus sign-in, evidence, job, assessment, and candidate submission surfaces |
| React/TypeScript production build | Passed |
| Browser runtime errors in public and staff visual checks | None observed |
| Responsive layout checks | Six routes fit 320 px, 390 px, 768 px, and 1440 px viewports, with tables and pipeline scrolling inside their containers |
| Seeded private PDF/DOCX files | 20 |
| Existing SQLite workspace | Migrated an empty revision table and retained 20 candidates and 4 jobs |
| Python dependency advisory check | No known vulnerabilities reported for the pinned requirements after upgrading cryptography to 50.0.2 |
| Frontend dependency advisory check | One unresolved upstream picomatch advisory reported across four build dependencies |
| Portfolio recording | Existing nine-minute recording demonstrates the earlier interface |

The browser workflow creates a job, screens/reviews a fictional candidate, creates an assessment,
submits answers and future availability through the candidate invitation, reviews responses,
schedules a preview interview, records feedback, and saves a hired outcome. Separate scenarios
verify anonymous access, candidate search/source evidence, mobile navigation and focus restoration,
job-specific links, browser history, keyboard search, CSV formula escaping, stale-score handling,
network recovery, authentication races, admin role changes, and manager controls. The full journey
also corrects source text and checks preview Calendar availability.

The visual review covered overview, jobs, candidate lists, pipeline, analytics, settings,
staff access, evidence, job creation, resume upload, profile correction, and interview scheduling.
GSAP page/dialog entrances respect reduced-motion preferences. Fonts are served locally.
Automated accessibility checks supplement the keyboard and visual review.

Backend regressions cover role boundaries, fabricated evidence, persistent reviews after restart,
lease recovery, stale versions including edits during a model call, duplicate actions, invitation
expiry/renewal, encrypted invitation payloads, known quota-error recovery, ambiguous-delivery blocks,
model provenance/cache boundaries, private files, and fresh/reversible migrations. On Windows,
run `python scripts/verify_postgres.py --download --all-tests` to reproduce the full suite
with an isolated local PostgreSQL server.

Additional regressions cover concurrent admin demotions, duplicate screening approvals,
invitation replacement or expiry during submission, correct interview-task deduplication,
password whitespace, bounded unique MCQ choices, and seven-day Calendar query limits.

The extraction/ranking measurements in `evaluation.md` use the **deterministic demo provider**
and twenty author-labelled synthetic resumes. The November 18 rerun verified all 103 accepted
source quotes. Gemini quality and real hiring outcomes require separate evaluation.

## Dependency advisory still open

`npm audit` reports GHSA-fc5q-39xc-vjpf in picomatch 4.0.7, propagated through fdir,
tinyglobby, and Vite. The upstream advisory lists no patched release. Hireline uses these
packages during trusted-source builds and local development. Production serves the generated
static assets, and the application accepts no user-provided glob patterns. This limits the
exposure, but the advisory remains open until a patched dependency is available.
[Upstream advisory](https://github.com/advisories/GHSA-fc5q-39xc-vjpf)

The cryptography update addresses the upstream PKCS#7 decryption advisory. Existing authentication,
encrypted-token, and workflow tests pass with 50.0.2.
[Cryptography advisory](https://github.com/pyca/cryptography/security/advisories/GHSA-g6cj-pr64-35w5)

## Hosted Supabase checks

The dedicated Hireline project in Mumbai accepted the initial Alembic schema. All 14 tables in
the public schema had row-level security enabled. Both browser roles lacked direct SELECT grants
on all 14 tables. A request to the candidate endpoint with the project's publishable key
returned HTTP 401. The private resumes bucket had a 5 MiB file limit. The project's public
signing-key endpoint advertised ES256.

Public signup was enabled at verification time. Disable it in the project's Auth settings before
provisioning staff. FastAPI independently requires a provisioned staff record for workspace access.

## Remaining live checks

The local readiness check still reports missing Gemini credentials/model, Supabase service key
and PostgreSQL connection URLs, Resend credentials/inbox, and Google OAuth credentials/attendee
allowlist. Local mode remains deterministic screening with preview communication.

- Actual Gemini free-quota/model access and extraction/ranking quality.
- Resend delivery to the configured signup inbox.
- Real Google OAuth authorization, refresh, availability, and event delivery.
- Staff sign-in, private file upload/download and checkpoint recovery through the hosted API.
- Render deployment, cold starts, and provider-account quotas.

The provider tests use mocked responses. The [recorded workflow](../output/demo/hireline-end-to-end.mp4)
shows the earlier interface with deterministic screening and preview communication. The [caption file](../output/demo/hireline-demo.srt)
and [chapter timings](../output/demo/verification.json) accompany the recording.
