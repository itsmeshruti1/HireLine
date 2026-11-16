"""Isolate test processes from any real accounts configured in the workspace .env."""
import os

# Applied before test modules import the global application. Individual tests opt into
# their own fake configuration; provider SDKs/transports remain mocked.
os.environ.update({
    "APP_ENV": "test", "AUTH_MODE": "local", "AI_MODE": "demo", "EXTERNAL_MODE": "preview",
    "DATABASE_URL": "sqlite:///:memory:", "CHECKPOINT_URL": "sqlite:///:memory:",
    "APP_SECRET": "isolated-tests-never-a-production-secret", "SEED_DEMO": "false",
    "WORKER_ENABLED": "false", "SUPABASE_URL": "", "SUPABASE_ANON_KEY": "",
    "SUPABASE_SERVICE_ROLE_KEY": "", "GEMINI_API_KEY": "", "GEMINI_MODEL": "",
    "RESEND_API_KEY": "", "RESEND_TEST_INBOX": "", "GOOGLE_CLIENT_ID": "",
    "GOOGLE_CLIENT_SECRET": "", "TOKEN_ENCRYPTION_KEY": "", "CALENDAR_ALLOWED_EMAILS": "",
})
