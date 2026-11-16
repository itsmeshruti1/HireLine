"""Verify real PostgreSQL without installing a service or touching the app database.

Windows: --download uses the official EDB archive linked by postgresql.org.
Other platforms: point --bin-dir at an existing PostgreSQL bin directory.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
ARCHIVE_URL = "https://get.enterprisedb.com/postgresql/postgresql-16.15-1-windows-x64-binaries.zip"
ARCHIVE_SHA256 = "25e6fcdfb8caec38691bf461125e7564508760666f7b8e5dc6a5f0818f58f81e"
# Vendor-published digest: https://github.com/EnterpriseDB/edb-installers/issues/696


def binaries(download: bool, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    directory = CACHE / "postgres-16.15" / "pgsql" / "bin"
    if (directory / "postgres.exe").is_file():
        return directory
    if os.name != "nt" or not download:
        raise RuntimeError("Provide --bin-dir or, on Windows, run with --download.")
    archive = CACHE / "postgres-16.15.zip"
    if not archive.exists():
        print("Downloading official PostgreSQL binaries...", flush=True)
        urllib.request.urlretrieve(ARCHIVE_URL, archive)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != ARCHIVE_SHA256:
        raise RuntimeError("The PostgreSQL archive does not match the vendor checksum; it was not executed.")
    target = directory.parents[1].resolve()
    with ZipFile(archive) as package:
        members = [name for name in package.namelist()
                   if name.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/"))]
        if not all((target / name).resolve().is_relative_to(target) for name in members):
            raise RuntimeError("The PostgreSQL archive contains an unsafe path.")
        for name in members:
            package.extract(name, target)
    return directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--bin-dir")
    parser.add_argument("--all-tests", action="store_true")
    args = parser.parse_args()
    CACHE.mkdir(exist_ok=True)
    bin_dir = binaries(args.download, args.bin_dir)
    suffix = ".exe" if os.name == "nt" else ""
    postgres, initdb, pg_ctl = [bin_dir / (name + suffix) for name in ("postgres", "initdb", "pg_ctl")]
    if not all(program.is_file() for program in (postgres, initdb, pg_ctl)):
        raise RuntimeError("The chosen directory must contain postgres, initdb, and pg_ctl.")
    work = Path(tempfile.mkdtemp(prefix="postgres-check-", dir=CACHE))
    cluster = work / "cluster"
    password = secrets.token_hex(24)
    password_file = work / "initial-password"
    password_file.write_text(password, encoding="utf-8")
    try:
        subprocess.run([str(initdb), "-D", str(cluster), "-U", "recruiter_ci", "--encoding=UTF8",
                        "--locale=C", "--auth-host=scram-sha-256", "--auth-local=trust",
                        "--pwfile", str(password_file)], check=True, capture_output=True, text=True)
    finally:
        password_file.unlink(missing_ok=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    import psycopg
    url = f"postgresql+psycopg://recruiter_ci:{password}@127.0.0.1:{port}/postgres"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    version = subprocess.check_output([str(postgres), "--version"], text=True).strip()
    log = (work / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen([str(postgres), "-D", str(cluster), "-h", "127.0.0.1", "-p", str(port)],
                               stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError(f"PostgreSQL exited during startup. Inspect {work / 'server.log'}")
            try:
                with psycopg.connect(host="127.0.0.1", port=port, user="recruiter_ci", password=password,
                                     dbname="postgres", connect_timeout=1):
                    break
            except psycopg.OperationalError:
                time.sleep(.2)
        else:
            raise RuntimeError("The isolated PostgreSQL server did not become ready.")
        print(f"Verified engine: {version}. Running isolated database checks...", flush=True)
        command = [sys.executable, "-m", "pytest", "-q", "--basetemp", str(work / "pytest")]
        if not args.all_tests:
            command.append("backend/tests/test_postgres.py")
        result = subprocess.run(command, cwd=ROOT, env={**os.environ, "POSTGRES_TEST_URL": url})
        report = {"engine": version, "verified_at": datetime.now(timezone.utc).isoformat(),
                  "scope": "all backend tests" if args.all_tests else "PostgreSQL migration/checkpoint checks",
                  "exit_code": result.returncode, "isolated_local_server": True}
        (CACHE / "postgres-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return result.returncode
    finally:
        subprocess.run([str(pg_ctl), "-D", str(cluster), "-m", "fast", "-w", "stop"],
                       capture_output=True, text=True, timeout=20)
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=10)
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
