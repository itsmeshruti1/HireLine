"""Private local storage or Supabase private bucket access, called only by the API."""

import os
import re
from pathlib import Path
from urllib.parse import quote

import httpx

from .errors import ServiceError


def setting(settings, name: str, default: str = "", aliases: tuple = ()):
    for key in (name, *aliases):
        if settings is not None:
            value = settings.get(key) if isinstance(settings, dict) else getattr(settings, key, None)
            if value is not None:
                return value
        value = os.getenv(key.upper())
        if value is not None:
            return value
    return default


class DocumentStorage:
    def __init__(self, settings=None, client: httpx.Client | None = None):
        self.root = Path(setting(settings, "local_storage_dir", "data/documents")).resolve()
        self.url = str(setting(settings, "supabase_url")).rstrip("/")
        self.key = str(setting(settings, "supabase_service_role_key", aliases=("service_role_key",)))
        self.bucket = str(setting(settings, "supabase_storage_bucket", "resumes", ("storage_bucket",)))
        self.client = client
        self.remote = bool(self.url and self.key)
        if self.remote and not re.fullmatch(r"[A-Za-z0-9._-]+", self.bucket):
            raise ServiceError("Configure a valid private storage bucket name.")

    def _path(self, key: str) -> Path:
        if not key or len(key) > 500 or "\\" in key or "\x00" in key:
            raise ServiceError("Invalid private document key.")
        path = (self.root / key).resolve()
        if path == self.root or not path.is_relative_to(self.root):
            raise ServiceError("Invalid private document key.")
        return path

    def _url(self, key: str, *, operation: str = "object") -> str:
        self._path(key)
        return f"{self.url}/storage/v1/{operation}/{quote(self.bucket, safe='')}/{quote(key, safe='/')}"

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {"apikey": self.key, **kwargs.pop("headers", {})}
        if not self.key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.key}"
        try:
            if self.client:
                response = self.client.request(method, url, headers=headers, **kwargs)
            else:
                with httpx.Client(timeout=20) as client:
                    response = client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ServiceError("Private storage is unreachable. Retry the upload.", retryable=True) from exc
        if response.status_code >= 400:
            raise ServiceError("Private document storage request failed. Check bucket permissions and configuration.")
        return response

    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        if self.remote:
            self._request("POST", self._url(key), content=content,
                          headers={"Content-Type": content_type, "x-upsert": "true"})
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return key

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if self.remote:
            return self._request("GET", self._url(key, operation="object/authenticated")).content
        if not path.is_file():
            raise ServiceError("This private resume file is no longer available. Upload it again.")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if self.remote:
            self._request("DELETE", f"{self.url}/storage/v1/object/{quote(self.bucket, safe='')}", json={"prefixes": [key]})
        elif path.exists():
            path.unlink()

    def signed_url(self, key: str, expires_in: int = 300) -> str:
        if not self.remote:
            raise ServiceError("Local documents must be downloaded through the authenticated document API.")
        expires_in = min(max(expires_in, 30), 300)
        result = self._request("POST", self._url(key, operation="object/sign"), json={"expiresIn": expires_in}).json()
        path = result.get("signedURL") or result.get("signedUrl")
        if not path or not isinstance(path, str) or not path.startswith("/object/sign/"):
            raise ServiceError("Private storage did not return a valid signed link.")
        return self.url + "/storage/v1" + path
