"""Show account readiness without printing tokens, passwords, or connection strings."""
from pathlib import Path
import json
import os

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
values = {**dotenv_values(ROOT / ".env"), **os.environ}
groups = {
    "Gemini": ["GEMINI_API_KEY", "GEMINI_MODEL"],
    "Supabase": ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL", "CHECKPOINT_URL"],
    "Resend": ["RESEND_API_KEY", "RESEND_TEST_INBOX"],
    "Google Calendar": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "CALENDAR_ALLOWED_EMAILS", "TOKEN_ENCRYPTION_KEY"],
}
report = {}
for name, keys in groups.items():
    missing = [key for key in keys if not values.get(key)]
    if name == "Supabase":
        missing.extend(key for key in ("DATABASE_URL", "CHECKPOINT_URL")
                       if values.get(key) and not str(values[key]).startswith(("postgresql", "postgres://")))
    report[name] = {"configured": not missing, "missing_or_invalid_fields": missing}
print(json.dumps({"env_file_exists": (ROOT / ".env").exists(), "services": report}, indent=2))
