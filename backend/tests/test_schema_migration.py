"""The startup column migration has to speak the deployed dialect, not just SQLite.

`_ensure_schema_columns` is a no-op on a fresh database — `create_all` already made every
column — so its ALTER statements only ever execute against a database that predates a
column. In practice that is the deployed Postgres, which is why a SQLite-flavoured `DATETIME`
type or a `BOOLEAN ... DEFAULT 0` in there fails at boot and takes the deploy down with it.
"""

import inspect as inspect_module
import re

import pytest
from sqlalchemy import create_engine, inspect, text

from backend.app.database import Base
import backend.app.main as main_module

# Columns the private chat rooms work added after the tables already existed in production.
LATER_COLUMNS = {
    "secret_chat_sessions": (
        "host_key", "message_ttl_seconds", "link_expires_at", "expires_at", "closed_at",
        "ai_tone", "ai_persona", "ai_autopilot", "ai_mimic_me",
    ),
    "secret_chat_messages": ("via_ai",),
    "chat_jobs": ("web_search",),
}


@pytest.fixture()
def legacy_schema(tmp_path, monkeypatch):
    """A database shaped like the deployed one: tables present, later columns missing.

    Built on its own throwaway engine rather than the suite's shared one. Mutating the
    shared schema here made this fail only when the whole suite ran, because another
    module's `reset_database` could rebuild the tables mid-fixture.
    """
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(bind=legacy_engine)
    # An indexed column cannot be dropped while its index stands (host_key has one), and
    # SQLite only sees the index as gone in a later transaction — hence two passes.
    inspector = inspect(legacy_engine)
    indexes = {
        index["name"]
        for table in LATER_COLUMNS
        for index in inspector.get_indexes(table)
        if index.get("name")
    }
    with legacy_engine.begin() as connection:
        for name in indexes:
            connection.execute(text(f"DROP INDEX IF EXISTS {name}"))
    with legacy_engine.begin() as connection:
        for table, columns in LATER_COLUMNS.items():
            for column in columns:
                # SQLite only learned DROP COLUMN in 3.35; both dialects have it now.
                connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))

    # _ensure_schema_columns reads the module-level engine, so point it at this one.
    monkeypatch.setattr(main_module, "engine", legacy_engine)
    yield legacy_engine
    legacy_engine.dispose()


def test_migration_adds_every_later_column_back(legacy_schema):
    main_module._ensure_schema_columns()
    inspector = inspect(legacy_schema)
    for table, columns in LATER_COLUMNS.items():
        present = {column["name"] for column in inspector.get_columns(table)}
        assert set(columns) <= present, f"{table} missing {set(columns) - present}"


def test_migration_is_idempotent(legacy_schema):
    main_module._ensure_schema_columns()
    # A second boot must not try to add what is already there.
    main_module._ensure_schema_columns()


@pytest.fixture()
def r2_era_secret_images(tmp_path, monkeypatch):
    """A `secret_images` table from before the R2 -> disk rename: `r2_key`, no `file_path`.

    This is the shape the deployed Postgres was actually in. The rename landed in the model
    only, and create_all never alters an existing table, so the deployed column kept its old
    name while the ORM started selecting the new one.
    """
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'r2.db'}")
    Base.metadata.create_all(bind=legacy_engine)
    inspector = inspect(legacy_engine)
    for index in inspector.get_indexes("secret_images"):
        if index.get("name"):
            with legacy_engine.begin() as connection:
                connection.execute(text(f"DROP INDEX IF EXISTS {index['name']}"))
    with legacy_engine.begin() as connection:
        connection.execute(text("ALTER TABLE secret_images DROP COLUMN data"))
        connection.execute(text("ALTER TABLE secret_images RENAME COLUMN file_path TO r2_key"))
    monkeypatch.setattr(main_module, "engine", legacy_engine)
    yield legacy_engine
    legacy_engine.dispose()


def test_migration_renames_the_r2_era_column_and_survives_boot(r2_era_secret_images):
    """The regression: the backfill selected `file_path` on a table that only had `r2_key`.

    The failure took the whole app down at startup, and because the ADD COLUMN shared the
    backfill's transaction, the rollback meant every later boot hit the identical error —
    the deploy could never recover on its own.
    """
    main_module._ensure_schema_columns()
    columns = {column["name"] for column in inspect(r2_era_secret_images).get_columns("secret_images")}
    assert "file_path" in columns, "the r2_key -> file_path rename never reached the database"
    assert "r2_key" not in columns
    assert "data" in columns, "the ADD COLUMN was rolled back by a failing backfill"


def test_migration_from_the_r2_era_is_idempotent(r2_era_secret_images):
    main_module._ensure_schema_columns()
    main_module._ensure_schema_columns()


def test_migration_emits_no_sqlite_only_ddl():
    """Guards the actual regression: `DATETIME` and `DEFAULT 0/1` booleans break Postgres.

    Reads the source rather than the code object: a tuple of literal statements is stored as
    a single tuple constant, so scanning `co_consts` for strings silently sees nothing.
    """
    source = inspect_module.getsource(main_module._ensure_schema_columns)
    ddl = [line.strip() for line in source.splitlines() if "ADD COLUMN" in line]
    assert ddl, "no ALTER statements found — has the migration moved?"
    for statement in ddl:
        assert " DATETIME" not in statement.upper(), (
            f"Postgres has no DATETIME type; take the type from the dialect: {statement}"
        )
        assert not re.search(r"BOOLEAN[^,]*DEFAULT\s+[01]\b", statement, re.IGNORECASE), (
            f"Postgres rejects 0/1 as a BOOLEAN default; use TRUE/FALSE: {statement}"
        )


def test_stream_terminates_when_the_worker_dies_before_its_try_block():
    """Both streaming endpoints must always emit their sentinel.

    `run()` queues the sentinel in a `finally`, but only once execution is inside its try
    block — a failure while opening the session happens before that. Without the guard the
    consumer loop blocks on an empty queue and the request hangs open forever.
    """
    source = inspect_module.getsource(main_module)
    # Counted against the streams themselves rather than a fixed number, so adding a
    # streaming endpoint without a guard fails here instead of silently passing.
    assert source.count("def run_guarded():") == source.count("def event_stream():"), (
        "a streaming endpoint lost its sentinel guard"
    )
    assert "Thread(target=run, daemon=True)" not in source, (
        "a stream still starts run() directly, so a pre-try failure would hang the response"
    )
