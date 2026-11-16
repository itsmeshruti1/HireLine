"""Apply tracked migrations and safely adopt the original local SQLite schema."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import UniqueConstraint, inspect, text

from .db import Base
from . import models  # Register tables before comparing the original local schema.


def _adopt_local_schema(connection, config):
    inspector = inspect(connection)
    present = set(inspector.get_table_names())
    expected = set(Base.metadata.tables)
    if not expected <= present:
        raise RuntimeError("The unversioned local database has an incomplete schema. Back it up and review it before migrating.")
    for table in Base.metadata.sorted_tables:
        actual_columns = {column["name"]: column for column in inspector.get_columns(table.name)}
        if set(actual_columns) != set(table.columns.keys()):
            raise RuntimeError(f"The unversioned local table {table.name} differs from the supported v1 schema. No records were changed.")
        for column in table.columns:
            actual = actual_columns[column.name]
            if actual["type"]._type_affinity is not column.type._type_affinity or bool(actual["nullable"]) != column.nullable:
                raise RuntimeError(f"The unversioned local column {table.name}.{column.name} is incompatible. No records were changed.")
        unique = {tuple(row["column_names"]) for row in inspector.get_unique_constraints(table.name)}
        unique.update(tuple(row["column_names"]) for row in inspector.get_indexes(table.name) if row["unique"])
        for constraint in table.constraints:
            columns = tuple(column.name for column in constraint.columns)
            if isinstance(constraint, UniqueConstraint) and columns not in unique:
                if table.name == "assessments" and columns == ("application_id",):
                    duplicate = connection.execute(text("SELECT application_id FROM assessments GROUP BY application_id HAVING COUNT(*) > 1 LIMIT 1")).first()
                    if duplicate:
                        raise RuntimeError("Legacy assessments contain duplicate applications. Back up and reconcile those records before migrating; no records were deleted.")
                    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_assessment_application ON assessments (application_id)"))
                else:
                    raise RuntimeError(f"The unversioned local table {table.name} is missing a unique constraint. No records were changed.")
    command.stamp(config, ScriptDirectory.from_config(config).get_base())


def prepare_database(engine, app_env):
    """Use Alembic on every startup; only the known local v1 schema can be adopted."""
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["configure_logger"] = False
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        business_tables = set(Base.metadata.tables) & tables
        versioned = "alembic_version" in tables and connection.execute(text("SELECT version_num FROM alembic_version")).first() is not None
        if business_tables and not versioned:
            if app_env == "production" or connection.dialect.name != "sqlite":
                raise RuntimeError("The database contains unversioned business tables. Back up and explicitly migrate the existing schema before starting production.")
            _adopt_local_schema(connection, config)
        command.upgrade(config, "head")
