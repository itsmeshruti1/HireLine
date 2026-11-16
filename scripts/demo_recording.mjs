/** Reproducible narrated demo. Own isolated services/data; never reads or mutates the user's workspace database. */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { spawn, spawnSync, execFileSync } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium, expect } = require('@playwright/test');
const verifyOnly = process.argv.includes('--verify-actions');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'scripts/demo_narration.json'), 'utf8'));
const apiPort = Number(process.env.DEMO_API_PORT ?? 8012);
const uiPort = Number(process.env.DEMO_UI_PORT ?? 5185);
const apiURL = `http://127.0.0.1:${apiPort}`;
const uiURL = `http://127.0.0.1:${uiPort}`;
const output = path.join(root, 'output/demo');
const cacheRoot = path.join(root, '.cache');
fs.mkdirSync(cacheRoot, { recursive: true });
const scratch = fs.mkdtempSync(path.join(cacheRoot, 'demo-recording-'));
const voices = path.join(scratch, 'narration');
fs.mkdirSync(output, { recursive: true });
const python = path.join(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const children = [];
let browser; let context; let page; let recordingPath;
const state = {}; const timeline = []; let captureStarted = 0; let activeChapter = null;

function log(message) { process.stdout.write(`[demo] ${message}\n`); }
function run(binary, args, options = {}) {
  const result = spawnSync(binary, args, { cwd: root, encoding: 'utf8', windowsHide: true, ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${path.basename(binary)} failed: ${(result.stderr ?? result.stdout ?? '').slice(-2000)}`);
  return result;
}
function readWave(file) {
  const bytes = fs.readFileSync(file); let position = 12; let format; let pcm;
  if (bytes.toString('ascii', 0, 4) !== 'RIFF') throw new Error(`Invalid wave: ${file}`);
  while (position + 8 <= bytes.length) {
    const name = bytes.toString('ascii', position, position + 4); const length = bytes.readUInt32LE(position + 4);
    if (name === 'fmt ') format = bytes.subarray(position + 8, position + 8 + length);
    if (name === 'data') pcm = bytes.subarray(position + 8, position + 8 + length);
    position += 8 + length + (length % 2);
  }
  if (!format || !pcm || format.readUInt16LE(0) !== 1) throw new Error('Expected uncompressed PCM narration.');
  return { format, pcm, rate: format.readUInt32LE(8), align: format.readUInt16LE(12), seconds: pcm.length / format.readUInt32LE(8) };
}
function writeWave(file, format, pcm) {
  const fmt = Buffer.alloc(8); fmt.write('fmt '); fmt.writeUInt32LE(format.length, 4);
  const data = Buffer.alloc(8); data.write('data'); data.writeUInt32LE(pcm.length, 4);
  const header = Buffer.alloc(12); header.write('RIFF'); header.writeUInt32LE(4 + fmt.length + format.length + data.length + pcm.length, 4); header.write('WAVE', 8);
  fs.writeFileSync(file, Buffer.concat([header, fmt, format, data, pcm]));
}
function start(binary, args, env, name, workingDirectory = root) {
  const logfile = fs.openSync(path.join(scratch, `${name}.log`), 'w');
  const child = spawn(binary, args, { cwd: workingDirectory, env: { ...process.env, ...env }, windowsHide: true, stdio: ['ignore', logfile, logfile] });
  children.push(child); child.on('error', error => log(`${name} startup error: ${error.message}`));
  return child;
}
async function waitService(url, child, name) {
  for (let i = 0; i < 120; i++) {
    if (child.exitCode !== null) throw new Error(`${name} exited; see ${scratch}/${name}.log`);
    try { const response = await fetch(url, { signal: AbortSignal.timeout(2000) }); if (response.ok) return; } catch {}
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error(`${name} did not become ready.`);
}
async function api(pathname) {
  const token = await page.evaluate(() => sessionStorage.getItem('hireline_token'));
  const response = await fetch(`${apiURL}/api${pathname}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) throw new Error(`Read ${pathname}: ${response.status}`);
  return response.json();
}
async function until(test, name, timeout = 35000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const result = await test(); if (result) return result; await new Promise(resolve => setTimeout(resolve, 400)); }
  throw new Error(`Timed out waiting for ${name}`);
}
async function click(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (box && !verifyOnly) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 9 });
  await locator.click(); if (!verifyOnly) await page.waitForTimeout(220);
}
async function fill(locator, value) {
  await locator.scrollIntoViewIfNeeded(); await locator.fill('');
  if (verifyOnly) await locator.fill(value); else await locator.pressSequentially(value, { delay: 13 });
}
async function holdUntil(fraction) {
  if (verifyOnly || !activeChapter) return;
  const wait = activeChapter.started + activeChapter.seconds * 1000 * fraction - Date.now();
  if (wait > 0) await page.waitForTimeout(wait);
}
async function login(email) {
  await click(page.getByRole('button', { name: 'Staff sign in', exact: true }));
  await fill(page.getByLabel('Email address', { exact: true }), email);
  await page.getByLabel('Password', { exact: true }).fill('local-demo-only');
  await click(page.getByRole('button', { name: 'Sign in to workspace', exact: true }));
  await expect(page.getByRole('button', { name: 'Sign out', exact: true })).toBeVisible();
}
async function navigate(name) { await click(page.getByRole('navigation').getByRole('button', { name: name === 'Candidates' ? /^Candidates/ : name, exact: name !== 'Candidates' })); }
async function openCandidate() {
  await navigate('Candidates');
  await page.getByRole('combobox', { name: 'Filter by job', exact: true }).selectOption(state.jobId);
  await fill(page.getByRole('textbox', { name: 'Filter candidates', exact: true }), 'Mira Rowan');
  await click(page.getByRole('button', { name: 'View Mira Rowan', exact: true }));
}
async function closeDialog() { await click(page.getByRole('button', { name: 'Close dialog', exact: true }).last()); }

function slideHTML(kind) {
  const evaluation = JSON.parse(fs.readFileSync(path.join(root, 'docs/evaluation.json'), 'utf8'));
  const shared = `<style>*{box-sizing:border-box}body{margin:0;background:#f8f8fb;color:#36313f;font-family:'Segoe UI',sans-serif;padding:65px 85px}small{color:#9586a4;letter-spacing:.12em;font-size:13px}.brand{font-weight:700;font-size:27px;letter-spacing:-1px;color:#8e74b8}h1{font-size:46px;font-weight:550;letter-spacing:-2px;line-height:1.18;margin:23px 0 16px}h2{font-size:21px;font-weight:500;margin:0 0 13px}p{font-size:18px;line-height:1.7;color:#8b7b99;max-width:1100px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:32px}.card{background:white;border:1px solid #e7dfee;border-radius:13px;padding:25px}.value{font-size:45px;font-weight:500;letter-spacing:-2px;color:#8a70ab}.label{font-size:14px;color:#9a88a9;margin-top:10px;line-height:1.6}.pill{font-size:13px;display:inline-block;background:#eee6f8;color:#9879b4;padding:8px 13px;border-radius:7px}.node{background:white;border:1px solid #dfd2e9;border-radius:10px;padding:17px 20px;font-size:17px;color:#8d6fa3}.arrow{text-align:center;font-size:25px;color:#b59bc8;margin:5px}.flow{width:60%;margin:25px auto}.row{display:flex;gap:18px;justify-content:center}.row>.node{flex:1;text-align:center}.footer{position:absolute;bottom:90px;left:85px;color:#9d8ba9;font-size:14px;right:85px;border-top:1px solid #e5dced;padding-top:20px}.note{font-size:15px;color:#a18bae;line-height:1.8;margin-top:20px}.check{color:#7b9b86}.source{font-size:12px;color:#afa0bb;margin-top:18px}.left{width:54%}.architecture{display:flex;gap:55px}.architecture .flow{width:51%;margin:20px 0 0}.architecture .notes{width:43%;margin-top:23px}.notes .card{margin-bottom:16px;padding:18px 22px}.notes p{font-size:15px;line-height:1.65;margin:0}.title-rule{display:inline-block;width:50px;height:4px;background:#b6a0d5;border-radius:5px;margin-top:12px}</style>`;
  if (kind === 'evaluation') return `${shared}<div class="brand">hireline.</div><small>MEASURED BEHAVIOR · SYNTHETIC DATASET</small><h1>Useful measurements.<br>Honest limitations.</h1><p>Evaluate extraction and ranking separately. An impressive percentage needs a clear denominator and a meaningful comparison.</p><div class="grid"><div class="card"><div class="value">${evaluation.resumes}</div><div class="label">fictional resumes<br>Three software roles</div></div><div class="card"><div class="value">${(evaluation.skill_recall * 100).toFixed(1)}%</div><div class="label">skill recall<br>Reported separately from scalar fields</div></div><div class="card"><div class="value">${evaluation.verified_source_quotes}/${evaluation.accepted_source_quotes}</div><div class="label">accepted quotations found<br>in their referenced source text</div></div></div><div class="grid">${evaluation.rankings.map(row => `<div class="card"><h2>${row.job}</h2><div class="value">${(row.precision_at_5 * 100).toFixed(0)}%</div><div class="label">Top-five precision · Demo matcher<br>Keyword baseline: ${(row.keyword_precision_at_5 * 100).toFixed(0)}%</div></div>`).join('')}</div><div class="note">Demo and keyword baseline tie on this fixture. These results do not establish real-world hiring validity or Gemini superiority.</div><div class="footer">Actual local report: docs/evaluation.json · Mode: ${evaluation.mode} · No live-model benchmark claimed</div>`;
  if (kind === 'architecture') return `${shared}<div class="brand">hireline.</div><small>ARCHITECTURE OVERVIEW</small><h1>A complete workflow.<br>A focused architecture.</h1><div class="architecture"><div class="flow"><div class="node">React + TypeScript · Dashboard & candidate forms</div><div class="arrow">↓</div><div class="node">FastAPI · Validation, authorization & business records</div><div class="arrow">↓</div><div class="row"><div class="node">Leased task queue<br><span class="label">One worker</span></div><div class="node">LangGraph<br><span class="label">Persistent review pauses</span></div></div><div class="arrow">↓</div><div class="node">SQLAlchemy + Alembic · Relational data & migrations</div><div class="arrow">↓</div><div class="row"><div class="node">Local<br><span class="label">SQLite + private files</span></div><div class="node">Production path<br><span class="label">Postgres + Supabase Auth/Storage</span></div></div></div><div class="notes"><div class="card"><h2>Bounded AI workflow</h2><p>Structured extraction → criteria evaluation → source verification → human approval</p></div><div class="card"><h2>Explicit integration adapters</h2><p>Gemini · Resend · Google Calendar<br>Configured and smoke-tested independently</p></div><div class="card"><h2>Recovery and auditability</h2><p>Leases, checkpoints, action IDs, reviewer notes, and recorded pipeline transitions</p></div><div class="card"><h2>Small enough to understand</h2><p>No Redis, Celery cluster, microservice fleet, or vector database required for this release</p></div></div></div><div class="footer">Architecture explanation — not a screenshot of deployed infrastructure · Source: docs/architecture.md</div>`;
  return `${shared}<div class="brand">hireline.</div><small>PORTFOLIO RELEASE · SCOPE AND LIMITS</small><h1>Thoughtful hiring.<br>Grounded in evidence.</h1><p>A working path from job creation to a recorded outcome, with explicit human decisions and inspectable source evidence.</p><div class="grid"><div class="card"><span class="pill">DEMO + PREVIEW</span><h2 style="margin-top:20px">Honest recording modes</h2><p style="font-size:16px">Deterministic matching.<br>No external email or calendar delivery claimed.</p></div><div class="card"><span class="pill">SYNTHETIC ONLY</span><h2 style="margin-top:20px">Private by design</h2><p style="font-size:16px">Fictional resumes.<br>Role checks and narrow, expiring candidate invitations.</p></div><div class="card"><span class="pill">STRICTLY FREE</span><h2 style="margin-top:20px">Realistic availability</h2><p style="font-size:16px">Free services can sleep.<br>No paid fallback or always-on reminder promise.</p></div></div><div class="grid"><div class="card"><h2 class="check">✓ Source & setup</h2><div class="label">Reproducible local setup<br>Database migrations<br>Deployment instructions</div></div><div class="card"><h2 class="check">✓ Evidence & checks</h2><div class="label">Automated API/browser tests<br>Dataset and evaluation harness<br>Documented limitations</div></div><div class="card"><h2 class="check">✓ End-to-end journey</h2><div class="label">Resume → screening → assessment<br>Interview preview → feedback<br>Human-recorded hiring outcome</div></div></div><div class="footer">Hireline · A portfolio demonstration using an isolated fixture database · Real-account integration verification is a separate release step</div>`;
}

const actions = {
  async overview() {
    await page.goto(uiURL); await expect(page.getByRole('heading', { name: /Good (morning|afternoon|evening)/ })).toBeVisible();
    await holdUntil(.4); await page.getByText('Your hiring funnel', { exact: true }).scrollIntoViewIfNeeded();
    await holdUntil(.7); await page.getByText('Standout candidates', { exact: true }).scrollIntoViewIfNeeded();
  },
  async job() {
    await page.evaluate(() => window.scrollTo(0, 0)); await login('admin@demo.local');
    await click(page.getByRole('button', { name: 'Create a job', exact: true }));
    await fill(page.getByLabel('Job title', { exact: true }), 'Python Platform Engineer');
    await fill(page.getByLabel('Job description', { exact: true }), 'Build dependable Python APIs using FastAPI and PostgreSQL. Write automated tests and explain deployment tradeoffs. Kubernetes experience is useful and should be supported by concrete source evidence.');
    const manager = page.getByRole('checkbox', { name: 'Jordan Lee', exact: true }); if (await manager.count()) await manager.check();
    for (const [index, [name, weight]] of [['Python', 35], ['FastAPI', 25], ['PostgreSQL', 25], ['Kubernetes', 15]].entries()) {
      await click(page.getByRole('button', { name: 'Add criterion', exact: true }));
      await fill(page.getByLabel(`Criterion ${index + 1}`, { exact: true }), name);
      await page.getByRole('spinbutton', { name: `Criterion ${index + 1} weight`, exact: true }).fill(String(weight));
    }
    await holdUntil(.65); await page.getByRole('checkbox', { name: /reviewed and approve these criteria/ }).check();
    await click(page.getByRole('button', { name: 'Create job opening', exact: true }));
    await until(async () => { const data = await api('/workspace'); const job = data.jobs.find(j => j.title === 'Python Platform Engineer'); if (job) state.jobId = job.id; return job; }, 'created job');
    await navigate('Job openings'); await expect(page.getByRole('heading', { name: 'Python Platform Engineer', exact: true })).toBeVisible();
  },
  async upload() {
    await navigate('Candidates'); await click(page.getByRole('button', { name: 'Add candidates', exact: true }));
    await page.getByRole('combobox', { name: 'Job opening', exact: true }).selectOption(state.jobId);
    await page.getByLabel('Resume files', { exact: true }).setInputFiles([path.join(root, 'samples/resumes/candidate-01.pdf'), path.join(root, 'samples/resumes/candidate-02.docx')]);
    await holdUntil(.3); await page.getByRole('checkbox', { name: /These resumes contain fictional/ }).check();
    await click(page.getByRole('button', { name: 'Import 2 resumes', exact: true }));
    await until(async () => { const data = await api('/workspace'); const apps = data.applications.filter(a => a.job_id === state.jobId); return apps.length === 2 && apps.every(a => data.candidates.find(c => c.id === a.candidate_id)?.name !== 'candidate-01') && data.tasks.filter(t => t.kind === 'import').every(t => t.status === 'completed'); }, 'imported profiles');
    await page.waitForTimeout(3800); await page.getByRole('combobox', { name: 'Filter by job', exact: true }).selectOption(state.jobId);
  },
  async profile() {
    await fill(page.getByRole('textbox', { name: 'Filter candidates', exact: true }), 'Mira Rowan');
    await click(page.getByRole('button', { name: 'View Mira Rowan', exact: true }));
    await holdUntil(.25); await click(page.getByRole('button', { name: 'Edit profile', exact: true }));
    await fill(page.getByLabel('Headline', { exact: true }), 'Backend engineer · synthetic portfolio candidate');
    await holdUntil(.55); await click(page.getByRole('button', { name: 'Save profile corrections', exact: true }));
    await page.getByText('Skills & experience', { exact: true }).scrollIntoViewIfNeeded();
  },
  async screening() {
    await click(page.getByRole('tab', { name: 'Screening', exact: true }));
    await click(page.getByRole('button', { name: 'Start screening', exact: true }));
    await expect(page.getByRole('button', { name: 'Review screening', exact: true })).toBeVisible({ timeout: 35000 });
    await page.locator('.screening-summary').scrollIntoViewIfNeeded();
    await holdUntil(.4); await page.locator('.evidence-item').first().scrollIntoViewIfNeeded();
    await holdUntil(.7); await page.locator('.evidence-item').last().scrollIntoViewIfNeeded();
  },
  async review() {
    await click(page.getByRole('button', { name: 'Review screening', exact: true }));
    await fill(page.getByLabel('Review notes', { exact: true }), 'Reviewed the resume excerpts against the confirmed rubric. Kubernetes needs clarification; the supported Python API work justifies a conversation.');
    await holdUntil(.3); await click(page.getByRole('button', { name: 'Approve screening review', exact: true }));
    await expect(page.getByRole('heading', { name: 'Take a closer look', exact: true })).toHaveCount(0);
    await click(page.getByRole('button', { name: 'Update stage', exact: true }));
    await page.getByRole('combobox', { name: 'Application stage', exact: true }).selectOption('shortlisted');
    await fill(page.getByLabel(/Decision note/), 'Recruiter shortlisted for further job-relevant assessment after reviewing source evidence.');
    await holdUntil(.65); await click(page.getByRole('button', { name: 'Confirm stage change', exact: true }));
    await expect(page.locator('.candidate-detail-header')).toContainText('Shortlisted');
  },
  async assessment() {
    await click(page.getByRole('tab', { name: 'Assessment', exact: true }));
    await click(page.getByRole('button', { name: 'Create assessment', exact: true }));
    await holdUntil(.3); await page.getByText('Question 3', { exact: true }).scrollIntoViewIfNeeded();
    await holdUntil(.55); await page.getByRole('checkbox', { name: /I approve these questions and scoring criteria/ }).check();
    await click(page.getByRole('button', { name: 'Approve & create invitation', exact: true }));
    state.invite = await page.getByLabel('Candidate invitation link', { exact: true }).inputValue();
    if (!state.invite.startsWith(uiURL)) throw new Error('Invite points outside isolated recording instance.');
  },
  async candidate() {
    await page.goto(state.invite); await expect(page.getByRole('heading', { name: /Your experience/ })).toBeVisible();
    await page.getByRole('radio', { name: 'Parameterized queries', exact: true }).check();
    await page.getByRole('radio', { name: 'To make related operations atomic', exact: true }).check();
    await fill(page.getByRole('textbox', { name: /Describe a technical problem/ }), 'In this fictional project I built a Python API with parameterized SQL. I compared simple database queries with extra caching, chose the smaller design, and verified success and failure paths with automated tests.');
    await holdUntil(.45); await click(page.getByRole('button', { name: 'Add availability', exact: true }));
    state.future = await page.evaluate(() => { const start = new Date(); start.setDate(start.getDate() + 2); start.setHours(10, 0, 0, 0); const local = d => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); return { start: local(start), end: local(new Date(start.getTime() + 3600000)) }; });
    await page.getByLabel('Available from', { exact: true }).fill(state.future.start); await page.getByLabel('Until', { exact: true }).fill(state.future.end);
    await page.getByRole('checkbox', { name: /I am submitting fictional demo responses/ }).check();
    await holdUntil(.75); await click(page.getByRole('button', { name: 'Submit my responses', exact: true }));
    await expect(page.getByRole('heading', { name: /Thanks for sharing/ })).toBeVisible();
    await page.reload(); await expect(page.getByRole('heading', { name: /Thanks for sharing/ })).toBeVisible();
  },
  async assessment_review() {
    await page.goto(`${uiURL}/candidates`); await openCandidate();
    await click(page.getByRole('tab', { name: 'Assessment', exact: true }));
    await expect(page.getByText('MCQ score: 100', { exact: true })).toBeVisible();
    await holdUntil(.35); await click(page.getByRole('button', { name: 'Review responses', exact: true }));
    await fill(page.getByLabel('Reviewer notes', { exact: true }), 'Read the fictional responses against the approved rubric. The answer gives a concrete design tradeoff and a verification strategy. Proceed to an interview for clarification.');
    await page.getByRole('checkbox', { name: /I have reviewed the candidate responses/ }).check();
    await holdUntil(.65); await click(page.getByRole('button', { name: 'Record assessment review', exact: true }));
  },
  async interview() {
    await click(page.getByRole('tab', { name: 'Interviews', exact: true }));
    await click(page.getByRole('button', { name: 'Schedule interview', exact: true }));
    await expect(page.getByLabel('Interview start', { exact: true })).toHaveValue(state.future.start);
    await page.getByRole('checkbox', { name: /I approve this interview/ }).check();
    await click(page.getByRole('button', { name: 'Confirm interview booking', exact: true }));
    await expect(page.locator('.interview-detail')).toContainText('Preview', { timeout: 25000 });
    await holdUntil(.35); await click(page.getByRole('button', { name: 'Record interview feedback', exact: true }));
    await fill(page.getByLabel('Your observations', { exact: true }), 'The fictional candidate explained the API design, named its limits, and described meaningful tests. Kubernetes depth needs mentoring and was discussed explicitly.');
    await page.getByRole('combobox', { name: 'Assessment of job-relevant evidence', exact: true }).selectOption('4');
    await click(page.getByRole('button', { name: 'Save team feedback', exact: true }));
    await click(page.getByRole('button', { name: 'Update stage', exact: true }));
    await page.getByRole('combobox', { name: 'Application stage', exact: true }).selectOption('hired');
    await fill(page.getByLabel(/Decision note/), 'Fictional hiring outcome recorded by the recruiter after reviewing the rubric evidence, assessment, and interview feedback.');
    await holdUntil(.75); await click(page.getByRole('button', { name: 'Confirm stage change', exact: true }));
    await expect(page.locator('.candidate-detail-header')).toContainText('Hired');
  },
  async roles() {
    await closeDialog(); await click(page.getByRole('button', { name: 'Sign out', exact: true })); await login('manager@demo.local');
    await navigate('Job openings'); await expect(page.getByRole('button', { name: 'Create a job', exact: true })).toHaveCount(0);
    await openCandidate(); await expect(page.getByRole('button', { name: 'Update stage', exact: true })).toHaveCount(0);
    await holdUntil(.4); await closeDialog(); await click(page.getByRole('button', { name: 'Sign out', exact: true })); await login('admin@demo.local');
    await click(page.getByRole('button', { name: 'Settings', exact: true }));
    await page.getByText('Processing history', { exact: true }).scrollIntoViewIfNeeded();
  },
  async analytics() {
    await navigate('Analytics'); await page.getByText('Applications reaching each stage', { exact: true }).scrollIntoViewIfNeeded();
    await holdUntil(.43); await page.setContent(slideHTML('evaluation'));
  },
  async architecture() { await page.setContent(slideHTML('architecture')); },
  async limits() { await page.setContent(slideHTML('limits')); },
};

function assTime(value) { const n = Math.max(0, Math.round(value * 100)); return `${Math.floor(n/360000)}:${String(Math.floor(n/6000)%60).padStart(2,'0')}:${String(Math.floor(n/100)%60).padStart(2,'0')}.${String(n%100).padStart(2,'0')}`; }
function srtTime(value) { return assTime(value).replace(/\.(\d\d)$/, ',$10').replace(/^(\d):/, '0$1:'); }
function escapeASS(value) { return value.replaceAll('{', '(').replaceAll('}', ')').replaceAll('\n', '\\N'); }
function writeCaptions(speed) {
  const header = `[Script Info]\nScriptType: v4.00+\nPlayResX: 1440\nPlayResY: 900\nWrapStyle: 0\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Subtitle,Segoe UI,23,&H00FFFFFF,&H00FFFFFF,&H90000000,&H90000000,0,0,0,0,100,100,0,0,3,1.6,0,2,80,80,24,1\nStyle: Chapter,Segoe UI,20,&H00FFFFFF,&H00FFFFFF,&H80000000,&H80000000,-1,0,0,0,100,100,0,0,3,1,0,7,24,24,16,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n`;
  const events = []; const srt = []; let index = 1;
  for (const chapter of timeline) {
    events.push(`Dialogue: 1,${assTime(chapter.start/speed)},${assTime((chapter.end-.2)/speed)},Chapter,,0,0,0,,${escapeASS(chapter.title)}`);
    const words = chapter.text.split(/\s+/); const size = 13; const chunkCount = Math.ceil(words.length/size);
    for (let i = 0; i < chunkCount; i++) {
      const chunk = words.slice(i*size, (i+1)*size).join(' '); const start = chapter.start + 1 + chapter.audioSeconds * i / chunkCount; const end = chapter.start + 1 + chapter.audioSeconds * (i+1) / chunkCount;
      events.push(`Dialogue: 0,${assTime(start/speed)},${assTime(end/speed)},Subtitle,,0,0,0,,${escapeASS(chunk)}`);
      srt.push(`${index++}\n${srtTime(start/speed)} --> ${srtTime(end/speed)}\n${chunk}\n`);
    }
  }
  fs.writeFileSync(path.join(output, 'hireline-demo.ass'), header + events.join('\n') + '\n');
  fs.writeFileSync(path.join(output, 'hireline-demo.srt'), srt.join('\n'));
}

try {
  log(`Isolated run: ${path.basename(scratch)} · ${verifyOnly ? 'action verification' : 'narrated recording'}`);
  for (const url of [apiURL, uiURL]) { let exists = false; try { await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(1000) }); exists = true; } catch {} if (exists) throw new Error(`Port already in use: ${url}. Choose different DEMO_API_PORT/DEMO_UI_PORT.`); }
  const env = {
    APP_ENV: 'test', AUTH_MODE: 'local', AI_MODE: 'demo', EXTERNAL_MODE: 'preview',
    DATABASE_URL: `sqlite:///${path.join(scratch, 'app.db').replaceAll('\\','/')}`,
    CHECKPOINT_URL: `sqlite:///${path.join(scratch, 'checkpoints.db').replaceAll('\\','/')}`,
    LOCAL_STORAGE_DIR: path.join(scratch, 'documents'), SEED_DEMO: 'true', WORKER_ENABLED: 'true',
    APP_SECRET: 'isolated-video-demonstration-secret-never-production', FRONTEND_URL: uiURL, API_URL: apiURL,
    SUPABASE_URL: '', SUPABASE_ANON_KEY: '', SUPABASE_SERVICE_ROLE_KEY: '', GEMINI_API_KEY: '', GEMINI_MODEL: '',
    RESEND_API_KEY: '', RESEND_TEST_INBOX: '', GOOGLE_CLIENT_ID: '', GOOGLE_CLIENT_SECRET: '',
    GOOGLE_REDIRECT_URI: `${apiURL}/api/integrations/calendar/callback`, CALENDAR_ALLOWED_EMAILS: '', TOKEN_ENCRYPTION_KEY: '',
  };
  const backend = start(python, ['-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend', '--host', '127.0.0.1', '--port', String(apiPort), '--no-access-log'], env, 'api');
  const frontend = start(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', String(uiPort), '--strictPort'], { VITE_API_URL: '', VITE_API_PROXY_TARGET: apiURL }, 'ui', path.join(root, 'frontend'));
  log('Waiting for isolated services.');
  await Promise.all([waitService(`${apiURL}/api/health`, backend, 'api'), waitService(uiURL, frontend, 'ui')]);
  log('Isolated services ready.');
  const safeConfig = await fetch(`${apiURL}/api/config`).then(r => r.json());
  if (safeConfig.ai_mode !== 'demo' || safeConfig.external_mode !== 'preview' || safeConfig.auth_mode !== 'local') throw new Error('Recording service mode safety check failed.');
  if (!verifyOnly) {
    log('Synthesizing original narration with installed Windows speech voice.');
    run('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(root, 'scripts/demo_narrate.ps1'), '-Manifest', path.join(root, 'scripts/demo_narration.json'), '-OutputDirectory', voices]);
    for (const chapter of manifest.chapters) chapter.wave = readWave(path.join(voices, `${chapter.id}.wav`));
    log(`Narration ready: ${manifest.chapters.reduce((sum,c) => sum+c.wave.seconds,0).toFixed(1)} seconds across ${manifest.chapters.length} chapters.`);
  }
  browser = await chromium.launch({ channel: process.env.DEMO_BROWSER_CHANNEL ?? 'msedge', headless: true });
  context = await browser.newContext({ viewport: { width: 1440, height: 900 }, timezoneId: 'Asia/Kolkata', colorScheme: 'light', reducedMotion: 'reduce', ...(verifyOnly ? {} : { recordVideo: { dir: path.join(scratch, 'video'), size: { width: 1440, height: 900 } } }) });
  await context.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      const cursor = document.createElement('div'); cursor.id = 'demo-recording-pointer';
      cursor.style.cssText = 'position:fixed;width:19px;height:19px;border:2px solid #8b65b9;background:#a882cd30;border-radius:50%;pointer-events:none;z-index:2147483647;left:-40px;top:-40px;transition:width .1s,height .1s;';
      document.body.append(cursor); document.addEventListener('mousemove', event => { cursor.style.left = `${event.clientX-9}px`; cursor.style.top = `${event.clientY-9}px`; });
      document.addEventListener('click', () => { cursor.animate([{ transform: 'scale(1)' }, { transform: 'scale(1.9)', opacity: .4 }, { transform: 'scale(1)', opacity: 1 }], { duration: 320 }); });
    });
  });
  page = await context.newPage(); page.setDefaultTimeout(25000);
  const recording = page.video(); captureStarted = Date.now();
  for (const chapter of manifest.chapters) {
    const started = Date.now(); const seconds = verifyOnly ? 0 : chapter.wave.seconds + 2.2;
    activeChapter = { started, seconds }; log(chapter.title);
    await actions[chapter.id]();
    if (!verifyOnly) { const remaining = started + seconds*1000 - Date.now(); if (remaining > 0) await page.waitForTimeout(remaining); }
    timeline.push({ id: chapter.id, title: chapter.title, text: chapter.text, start: (started-captureStarted)/1000, end: (Date.now()-captureStarted)/1000, audioSeconds: chapter.wave?.seconds ?? 0 });
  }
  await page.screenshot({ path: path.join(output, verifyOnly ? 'action-verification.png' : 'recording-final-frame.png') });
  await page.close(); await context.close(); context = null;
  if (recording) recordingPath = await recording.path();
  await browser.close(); browser = null;
  if (verifyOnly) {
    fs.writeFileSync(path.join(output, 'action-verification.json'), JSON.stringify({ verified_at: new Date().toISOString(), isolated: true, ai_mode: 'demo', external_mode: 'preview', chapters: timeline.map(c => ({ id: c.id, seconds: c.end-c.start })), result: 'passed' }, null, 2));
    log('All recorded workflow actions verified. No external API calls or user database changes.');
  } else {
    const first = manifest.chapters[0].wave; const parts = []; let samplesWritten = 0;
    const addSilenceUntil = seconds => { const bytes = Math.max(0, Math.floor(seconds * first.rate / first.align) * first.align - samplesWritten); if (bytes) { parts.push(Buffer.alloc(bytes)); samplesWritten += bytes; } };
    for (let i = 0; i < timeline.length; i++) {
      const chapter = timeline[i]; const wave = manifest.chapters[i].wave;
      if (!wave.format.equals(first.format)) throw new Error('Narration PCM formats differ.');
      addSilenceUntil(chapter.start + 1); parts.push(wave.pcm); samplesWritten += wave.pcm.length;
    }
    const duration = timeline.at(-1).end; addSilenceUntil(duration);
    const audio = path.join(scratch, 'narration.wav'); writeWave(audio, first.format, Buffer.concat(parts));
    const speed = duration / manifest.target_seconds;
    if (speed < .75 || speed > 1.4) throw new Error(`Capture timing would require unnatural narration speed ${speed.toFixed(2)}.`);
    writeCaptions(speed);
    const ffmpeg = process.env.DEMO_FFMPEG ?? execFileSync(python, ['-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'], { cwd: root, encoding: 'utf8', windowsHide: true }).trim();
    log(`Compositing ${manifest.target_seconds}s MP4, narration tempo ${speed.toFixed(3)}.`);
    run(ffmpeg, ['-y', '-i', recordingPath, '-i', audio, '-vf', `fps=15,setpts=PTS/${speed.toFixed(8)},subtitles=hireline-demo.ass`, '-af', `atempo=${speed.toFixed(8)}`, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', '-t', String(manifest.target_seconds), 'hireline-end-to-end.mp4'], { cwd: output, maxBuffer: 16*1024*1024 });
    const video = path.join(output, 'hireline-end-to-end.mp4');
    const check = run(ffmpeg, ['-i', video, '-af', 'volumedetect', '-f', 'null', '-'], { maxBuffer: 16*1024*1024 });
    const details = check.stderr;
    const measured = details.match(/Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)/);
    const measuredDuration = measured ? Number(measured[1])*3600 + Number(measured[2])*60 + Number(measured[3]) : NaN;
    if (!details.includes('Audio: aac') || !details.includes('Video: h264') || details.includes('max_volume: -inf') || !Number.isFinite(measuredDuration) || Math.abs(measuredDuration-manifest.target_seconds) > .5) throw new Error('Video/audio/duration verification failed.');
    const frames = path.join(output, 'frames'); fs.mkdirSync(frames, { recursive: true });
    for (const second of [12, 95, 195, 295, 395, 495]) run(ffmpeg, ['-y', '-ss', String(second), '-i', video, '-frames:v', '1', path.join(frames, `frame-${second}.png`)], { maxBuffer: 2*1024*1024 });
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({ generated_at: new Date().toISOString(), video: 'hireline-end-to-end.mp4', duration_seconds: measuredDuration, target_duration_seconds: manifest.target_seconds, resolution: [1440,900], codecs: { video: 'h264', audio: 'aac' }, narrated: true, captions: 'Burned-in ASS and sidecar SRT', narration_voice: manifest.voice, modes: safeConfig, database: 'fresh isolated SQLite fixture; user database untouched', external_delivery: 'preview only; no live email/calendar claim', input_narration_seconds: manifest.chapters.reduce((sum,c) => sum+c.wave.seconds,0), tempo_factor: speed, bytes: fs.statSync(video).size, chapters: timeline.map(c => ({ id: c.id, title: c.title, start_seconds: +(c.start/speed).toFixed(2), end_seconds: +(c.end/speed).toFixed(2) })), audio_decode_verified: true }, null, 2));
    log(`Verified output: ${video}`);
  }
} catch (error) {
  if (page && !page.isClosed()) await page.screenshot({ path: path.join(scratch, 'failure.png') }).catch(() => {});
  log(`FAILED: ${error.stack ?? error}`); process.exitCode = 1;
} finally {
  if (context) await context.close().catch(() => {}); if (browser) await browser.close().catch(() => {});
  for (const child of children.reverse()) {
    if (child.exitCode === null) {
      if (process.platform === 'win32') spawnSync('taskkill.exe', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore' });
      else child.kill('SIGTERM');
    }
  }
  log(`Run logs retained in ${scratch}`);
}
