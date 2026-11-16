# Reproduce the narrated portfolio recording

The recorder drives the real application with Playwright and Microsoft Edge, synthesizes the original
script with the installed **Microsoft Zira Desktop** Windows voice, and composes an H.264/AAC MP4
with burned-in captions. It does not require an AI speech service or paid account.

## Prerequisites

- Windows with the Zira Desktop `System.Speech` voice installed.
- The normal backend virtual environment and frontend dependencies from the project setup.
- Microsoft Edge, plus Playwright's small FFmpeg recorder binary (`npx playwright install ffmpeg`
  from `frontend/` if it is missing).
- The full FFmpeg binary supplied by `imageio-ffmpeg`:

```powershell
rtk proxy uv pip install --python .venv/Scripts/python.exe -r scripts/demo-requirements.txt
```

## Verify and record

Run from the repository root. These commands need permission to launch local servers, Edge, and
Windows speech outside a restricted execution sandbox.

```powershell
rtk proxy node scripts/demo_recording.mjs --verify-actions
rtk proxy node scripts/demo_recording.mjs
```

The first command executes every workflow action quickly. The second records the same journey
with chapter narration, source-linked captions, evaluation results, and an architecture explanation.
Allow roughly ten minutes for capture plus composition. The final MP4 targets **9 minutes**.

The recorder starts an isolated API on port `8012` and frontend on `5185`. It creates a fresh
SQLite database, checkpoints, and documents under a new `.cache/demo-recording-*` directory.
It explicitly forces `APP_ENV=test`, local authentication, deterministic demo matching, and preview
integrations, while overriding all provider credentials to empty strings. The user's ordinary
workspace database and live integration configuration are not changed. Owned helper processes
are stopped when the run finishes.

If either port is occupied, select unused ports through `DEMO_API_PORT` and `DEMO_UI_PORT`.
`DEMO_BROWSER_CHANNEL` defaults to `msedge`; `DEMO_FFMPEG` can select another full FFmpeg binary.

## Outputs

- `output/demo/hireline-end-to-end.mp4` — narrated application recording, burned-in captions.
- `output/demo/hireline-demo.srt` — portable sidecar captions.
- `output/demo/hireline-demo.ass` — compositing captions and chapter labels.
- `output/demo/verification.json` — duration, codecs, mode, chapter timings, and full-decode check.
- `output/demo/frames/` — representative frames for visual review.
- `output/demo/action-verification.json` — the fast workflow-check result.

Narration is in `scripts/demo_narration.json`; the PowerShell voice adapter is
`scripts/demo_narrate.ps1`. The evaluation slide reads the actual `docs/evaluation.json` report.
The recording labels deterministic matching and preview actions explicitly and does not claim
that any real email, calendar event, provider account, or production deployment was verified.

Captions use approximate word timing derived from each synthesized chapter, rather than claiming
forced-alignment accuracy. The recording speed is adjusted slightly to the nine-minute target;
the script rejects a tempo change outside a conservative range.
