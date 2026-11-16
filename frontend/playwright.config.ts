import { defineConfig } from '@playwright/test';

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5174';
const backend = process.env.PLAYWRIGHT_API_URL ?? 'http://127.0.0.1:8001';
const python = process.env.CI ? 'python' : process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python';

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL,
    channel: process.env.PLAYWRIGHT_CHANNEL ?? (process.platform === 'win32' ? 'msedge' : undefined),
    viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVERS === '1' ? undefined : [
    { command: `"${python}" ../scripts/e2e_backend.py`, url: `${backend}/api/health`,
      reuseExistingServer: false, timeout: 120_000 },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5174 --strictPort', url: baseURL,
      env: { VITE_API_URL: '', VITE_API_PROXY_TARGET: backend }, reuseExistingServer: false, timeout: 60_000 },
  ],
});
