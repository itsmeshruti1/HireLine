"""Isolated synthetic API instance used by Playwright, never a user's workspace database."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
cache = ROOT / ".cache"
cache.mkdir(exist_ok=True)
directory = Path(tempfile.mkdtemp(prefix="e2e-", dir=cache))
os.chdir(ROOT)
os.environ.update({
    "APP_ENV": "test", "AUTH_MODE": "local", "AI_MODE": "demo", "EXTERNAL_MODE": "preview",
    "DATABASE_URL": "sqlite:///" + (directory / "app.db").as_posix(),
    "CHECKPOINT_URL": "sqlite:///" + (directory / "checkpoints.db").as_posix(),
    "LOCAL_STORAGE_DIR": str(directory / "documents"), "SEED_DEMO": "true", "WORKER_ENABLED": "true",
    "APP_SECRET": "playwright-isolated-fixture-secret-never-production",
    "FRONTEND_URL": "http://127.0.0.1:5174", "API_URL": "http://127.0.0.1:8001",
    "SUPABASE_URL": "", "SUPABASE_ANON_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": "",
})
sys.path.insert(0, str(ROOT / "backend"))
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, access_log=False)
