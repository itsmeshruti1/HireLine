from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def now():
    return datetime.now(timezone.utc)


def as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


def make_database(url):
    if url.startswith("sqlite"):
        from pathlib import Path
        file = url.removeprefix("sqlite:///")
        if file != ":memory:":
            Path(file).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def sqlite_pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
    else:
        engine = create_engine(url, pool_size=2, max_overflow=0, pool_pre_ping=True)
    return engine, sessionmaker(engine, expire_on_commit=False)


def serialize(obj, exclude=()):
    result = {}
    for column in obj.__table__.columns:
        if column.name in exclude:
            continue
        value = getattr(obj, column.name)
        if isinstance(value, datetime):
            value = as_utc(value).isoformat()
        if column.name == "result" and isinstance(value, dict):
            value = {key: item for key, item in value.items() if not key.startswith("_")}
        result[column.name] = value
    return result
