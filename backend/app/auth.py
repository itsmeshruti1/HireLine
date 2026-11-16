from datetime import timedelta
from functools import lru_cache
import secrets
import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from .db import now, serialize
from .models import User


bearer = HTTPBearer(auto_error=False)


@lru_cache(maxsize=4)
def jwks_client(issuer):
    return jwt.PyJWKClient(issuer + "/.well-known/jwks.json", cache_keys=True, lifespan=300, timeout=10)


def login(settings, session, email, password):
    if settings.auth_mode == "local":
        if settings.app_env not in {"local", "test"}:
            raise HTTPException(403, "Local authentication is disabled")
        if not secrets.compare_digest(password, "local-demo-only"):
            raise HTTPException(401, "Invalid email or password")
        user = session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            raise HTTPException(401, "Invalid email or password")
        token = jwt.encode({"sub": user.id, "iss": "recruiter-local", "aud": "recruiter", "exp": now() + timedelta(hours=8)}, settings.app_secret, algorithm="HS256")
        return {"access_token": token, "user": serialize(user)}
    try:
        response = httpx.post(settings.supabase_url.rstrip("/") + "/auth/v1/token?grant_type=password", headers={"apikey": settings.supabase_anon_key}, json={"email": email, "password": password}, timeout=20)
        if response.status_code in {400, 401, 403}:
            raise HTTPException(401, "Sign-in failed. Check your staff account credentials.")
        response.raise_for_status()
        token = response.json()["access_token"]
        user = authenticate_token(settings, session, token)
        return {"access_token": token, "user": serialize(user)}
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(503, "The authentication service is unavailable. Please try signing in again shortly.")


def authenticate_token(settings, session, token):
    try:
        if settings.auth_mode == "local":
            claims = jwt.decode(token, settings.app_secret, algorithms=["HS256"], issuer="recruiter-local", audience="recruiter", options={"require": ["exp", "sub", "iss", "aud"]})
        else:
            issuer = settings.supabase_url.rstrip("/") + "/auth/v1"
            key = jwks_client(issuer).get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["ES256", "RS256"], issuer=issuer, audience="authenticated", options={"require": ["exp", "sub", "iss", "aud"]})
        user = session.get(User, claims["sub"])
        if user is None or user.role not in {"admin", "recruiter", "manager"}:
            raise HTTPException(403, "Your account has not been granted staff access")
        return user
    except HTTPException:
        raise
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, "The authentication service is unavailable. Please try again shortly.")
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Session expired or invalid. Please sign in again.")


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        raise HTTPException(401, "Sign in to access the recruiting workspace")
    with request.app.state.session_factory() as session:
        return authenticate_token(request.app.state.settings, session, credentials.credentials)


def recruiter(user=Depends(current_user)):
    if user.role not in {"admin", "recruiter"}:
        raise HTTPException(403, "Recruiter access is required")
    return user


def admin(user=Depends(current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin access is required")
    return user


def assert_job_access(user, job):
    if job is None:
        raise HTTPException(404, "Job not found")
    if user.role == "manager" and user.id not in job.manager_ids:
        raise HTTPException(403, "This job is not assigned to you")


def encryption(settings):
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    key = settings.token_encryption_key or base64.urlsafe_b64encode(hashlib.sha256(settings.app_secret.encode()).digest()).decode()
    return Fernet(key.encode())
