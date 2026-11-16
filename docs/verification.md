# Release verification

Verified on Windows with Python 3.12 and a headless Microsoft Edge browser.

| Check | Result |
| --- | --- |
| Backend/API/service/migration tests | 82 passed, zero skips, with PostgreSQL 16.15 available |
| PostgreSQL runtime | Durable checkpoint resume, concurrent requests, queue locks, provenance and time-zone handling passed |
| Browser scenarios | 3 passed |
| React/TypeScript production build | Passed |
| Browser runtime errors in read-only preview | None observed |
| Mobile overview width at 390 px | 390 px; table scroll stays inside its container |
| Seeded private PDF/DOCX files | 20 |
| Existing SQLite workspace | Migrated an empty revision table and retained 20 candidates and 4 jobs |
| Portfolio recording | Nine minutes, 14 chapters, 1440 × 900 H.264 video, AAC narration and captions |

The browser workflow creates a job, screens/reviews a fictional candidate, creates an assessment,
submits answers and future availability through the candidate invitation, reviews responses,
schedules a preview interview, records feedback, and saves a hired outcome. Separate scenarios
verify anonymous read-only access, candidate search/source evidence, and mobile navigation.

Backend regressions cover role boundaries, fabricated evidence, persistent reviews after restart,
lease recovery, stale versions including edits during a model call, duplicate actions, invitation
expiry/renewal, encrypted invitation payloads, known quota-error recovery, ambiguous-delivery blocks,
model provenance/cache boundaries, private files, and fresh/reversible migrations. On Windows,
run `python scripts/verify_postgres.py --download --all-tests` to reproduce the full suite
with an isolated local PostgreSQL server.

The extraction/ranking measurements in `evaluation.md` use the **deterministic demo provider**.
They are not measurements of Gemini, real candidates, or real hiring outcomes.

## Hosted Supabase checks

The dedicated Hireline project in Mumbai accepted the initial Alembic schema. All 14 tables in
the public schema had row-level security enabled. Both browser roles lacked direct SELECT grants
on all 14 tables. A request to the candidate endpoint with the project's publishable key
returned HTTP 401. The private resumes bucket had a 5 MiB file limit. The project's public
signing-key endpoint advertised ES256.

Public signup was enabled at verification time. Disable it in the project's Auth settings before
provisioning staff. FastAPI independently requires a provisioned staff record for workspace access.

## Remaining live checks

- Actual Gemini free-quota/model access and extraction/ranking quality.
- Resend delivery to the configured signup inbox.
- Real Google OAuth authorization, refresh, availability, and event delivery.
- Staff sign-in, private file upload/download and checkpoint recovery through the hosted API.
- Render deployment, cold starts, and provider-account quotas.

The provider tests use mocked responses. The [recorded workflow](../output/demo/hireline-end-to-end.mp4)
uses deterministic screening and preview communication. The [caption file](../output/demo/hireline-demo.srt)
and [chapter timings](../output/demo/verification.json) accompany the recording.
