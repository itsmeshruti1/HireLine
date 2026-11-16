import pytest
from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.db import make_database
from backend.app.migrations import prepare_database
from backend.app.models import Candidate, Document, Job
from backend.app.seed import seed_database
from backend.app.services.errors import ServiceError
from backend.app.services.storage import DocumentStorage


def test_seed_recovers_after_storage_failure_and_preserves_custom_records(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, app_env="test", auth_mode="local", ai_mode="demo", external_mode="preview", local_storage_dir=str(tmp_path / "files"), supabase_url="", supabase_service_role_key="")
    engine, factory = make_database("sqlite:///"+str(tmp_path / "seed.db"))
    prepare_database(engine, "test")
    with factory() as session:
        session.add(Job(id="custom-job", title="Preserve this role", description="Existing recruiter-created job"))
        session.commit()
    original_put = DocumentStorage.put
    calls = []
    def intermittently_unavailable(self, key, content, content_type="application/octet-stream"):
        calls.append(key)
        if len(calls) == 1:
            raise ServiceError("Mock private bucket is temporarily unavailable")
        return original_put(self, key, content, content_type)
    monkeypatch.setattr(DocumentStorage, "put", intermittently_unavailable)
    with pytest.raises(ServiceError):
        with factory() as session:
            seed_database(session, settings)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Job)) == 4
        assert session.scalar(select(func.count()).select_from(Candidate)) == 0
        seed_database(session, settings)
        assert session.scalar(select(func.count()).select_from(Candidate)) == 20
        assert session.scalar(select(func.count()).select_from(Document)) == 20
        assert session.get(Job, "custom-job").title == "Preserve this role"
    count = len(calls)
    with factory() as session:
        seed_database(session, settings)
        assert session.scalar(select(func.count()).select_from(Candidate)) == 20
    assert len(calls) == count
    engine.dispose()
