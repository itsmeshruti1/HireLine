"""Apply tracked migrations then run one production API/worker process."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ["PYTHONPATH"] = str(ROOT / "backend")
subprocess.run([sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", "backend",
                         "--host", "0.0.0.0", "--port", os.environ.get("PORT", "8000"), "--workers", "1"])
