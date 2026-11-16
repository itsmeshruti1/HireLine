"""Run both local apps; Ctrl+C stops the processes started by this script."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    args = parser.parse_args()
    venv = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python = str(venv) if venv.exists() else sys.executable
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not args.backend_only and (not npm or not (ROOT / "frontend/node_modules").exists()):
        print("Run npm install in frontend/ first, and ensure Node.js is installed.", file=sys.stderr)
        return 1
    commands = []
    if not args.frontend_only:
        commands.append(([python, "-m", "uvicorn", "app.main:app", "--app-dir", "backend",
                          "--host", "127.0.0.1", "--port", "8000"], ROOT))
    if not args.backend_only:
        commands.append(([npm, "run", "dev", "--", "--host", "127.0.0.1"], ROOT / "frontend"))
    children = []
    try:
        for command, cwd in commands:
            children.append(subprocess.Popen(command, cwd=cwd,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0))
        print("\nHireline: http://127.0.0.1:5173  |  API docs: http://127.0.0.1:8000/docs\n", flush=True)
        while True:
            for child in children:
                if child.poll() is not None:
                    return child.returncode
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                if os.name == "nt":
                    child.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    child.terminate()
        for child in children:
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    raise SystemExit(main())
