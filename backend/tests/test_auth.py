from datetime import timedelta
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
import httpx
import jwt
import pytest

from backend.app import auth
from backend.app.config import Settings
from backend.app.db import Base, make_database, now
from backend.app.models import User


@pytest.fixture
def identity(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, app_env="test", auth_mode="supabase", supabase_url="https://mock.supabase.co", supabase_anon_key="mock-public-key", app_secret="unit-test-secret-with-more-than-thirty-two-characters")
    engine, factory = make_database("sqlite:///"+str(tmp_path / "identity.db"))
    Base.metadata.create_all(engine)
    with factory() as session:
        session.add(User(id="staff-1", email="staff@example.test", name="Synthetic Staff", role="manager"))
        session.commit()
    key = ec.generate_private_key(ec.SECP256R1())
    client = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key()))
    monkeypatch.setattr(auth, "jwks_client", lambda issuer: client)
    with factory() as session:
        yield settings, session, key
    engine.dispose()


def token(key, **changes):
    claims = {"sub": "staff-1", "iss": "https://mock.supabase.co/auth/v1", "aud": "authenticated", "exp": now()+timedelta(minutes=5), "role": "admin"}
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="ES256")


def test_supabase_signature_and_database_role_are_authoritative(identity):
    settings, session, key = identity
    user = auth.authenticate_token(settings, session, token(key))
    assert user.id == "staff-1" and user.role == "manager"
    other_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(HTTPException) as invalid:
        auth.authenticate_token(settings, session, token(other_key))
    assert invalid.value.status_code == 401


@pytest.mark.parametrize("changes", [{"iss": "https://wrong-project/auth/v1"}, {"aud": "wrong-audience"}, {"exp": now()-timedelta(seconds=1)}])
def test_supabase_rejects_wrong_issuer_audience_and_expired_tokens(identity, changes):
    settings, session, key = identity
    with pytest.raises(HTTPException) as invalid:
        auth.authenticate_token(settings, session, token(key, **changes))
    assert invalid.value.status_code == 401


def test_supabase_requires_expiry_and_provisioned_staff(identity):
    settings, session, key = identity
    no_expiry = jwt.encode({"sub": "staff-1", "iss": "https://mock.supabase.co/auth/v1", "aud": "authenticated"}, key, algorithm="ES256")
    with pytest.raises(HTTPException) as invalid:
        auth.authenticate_token(settings, session, no_expiry)
    assert invalid.value.status_code == 401
    with pytest.raises(HTTPException) as unprovisioned:
        auth.authenticate_token(settings, session, token(key, sub="not-provisioned"))
    assert unprovisioned.value.status_code == 403


def test_jwks_outage_returns_retryable_service_status(identity, monkeypatch):
    settings, session, key = identity
    def unavailable(token):
        raise jwt.PyJWKClientConnectionError("Mock signing-key endpoint unavailable")
    monkeypatch.setattr(auth, "jwks_client", lambda issuer: SimpleNamespace(get_signing_key_from_jwt=unavailable))
    with pytest.raises(HTTPException) as unavailable_response:
        auth.authenticate_token(settings, session, token(key))
    assert unavailable_response.value.status_code == 503


def test_jwks_client_is_reused_for_same_project(monkeypatch):
    calls = []
    def constructor(url, **kwargs):
        calls.append((url, kwargs))
        return object()
    monkeypatch.setattr(jwt, "PyJWKClient", constructor)
    auth.jwks_client.cache_clear()
    try:
        assert auth.jwks_client("https://mock.supabase.co/auth/v1") is auth.jwks_client("https://mock.supabase.co/auth/v1")
        assert len(calls) == 1 and calls[0][1]["timeout"] == 10
    finally:
        auth.jwks_client.cache_clear()


@pytest.mark.parametrize("status,expected", [(400, 401), (401, 401), (429, 503), (503, 503)])
def test_password_login_distinguishes_invalid_credentials_from_provider_outage(identity, monkeypatch, status, expected):
    settings, session, key = identity
    response = httpx.Response(status, request=httpx.Request("POST", "https://mock.supabase.co/auth/v1/token"))
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)
    with pytest.raises(HTTPException) as result:
        auth.login(settings, session, "staff@example.test", "mock-password")
    assert result.value.status_code == expected


def test_postgres_urls_use_installed_driver_and_invalid_encryption_key_fails_early():
    settings = Settings(_env_file=None, app_env="test", database_url="postgres://user:password@localhost/db", checkpoint_url="postgres://user:password@localhost/db")
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.checkpoint_url.startswith("postgresql://")
    with pytest.raises(ValueError, match="valid Fernet key"):
        Settings(_env_file=None, app_env="test", token_encryption_key="not-a-fernet-key")
    with pytest.raises(ValueError) as invalid:
        Settings(_env_file=None, app_env="test", token_encryption_key="fake-sensitive-configuration-value")
    assert "fake-sensitive-configuration-value" not in str(invalid.value)


@pytest.mark.parametrize("field", ["database_url", "checkpoint_url"])
def test_local_demo_auth_cannot_use_hosted_supabase_database(field):
    with pytest.raises(ValueError, match="Set AUTH_MODE=supabase"):
        Settings(_env_file=None, auth_mode="local", **{field: "postgresql://example.pooler.supabase.com/postgres"})
