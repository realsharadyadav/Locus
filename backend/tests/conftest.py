"""Shared test setup.

Every test module talks to the same SQLAlchemy engine, because `backend.app.database`
builds it once at import time from `LOCUS_DATABASE_URL`. Pytest imports *all* test
modules before running any test, so a per-module `os.environ[...] = ...` only ever
took effect for whichever module happened to be imported first — the rest silently
shared that module's database and then had the file deleted out from under their
pooled connections ("attempt to write a readonly database").

conftest.py is imported before any test module, so setting the URL here is the one
place it reliably applies. Modules get isolation from `reset_database` instead of
from separate files.

LOCUS_UPLOAD_DIR gets the same treatment for the same reason, and it matters more: the
startup maintenance dead-file sweep (main.py's _startup_maintenance) deletes any file in
UPLOAD_DIR that has no matching StoredFile row in whatever database is attached. Point
that at a real local uploads/ folder while the test DB is an empty, freshly-reset schema,
and every real uploaded file looks orphaned and gets deleted — this already happened once
(1980 real files wiped by a single test run) before this isolation was added.
"""

import os
import shutil
import tempfile

os.environ.setdefault("LOCUS_DATABASE_URL", "sqlite:///./test_locus.db")
os.environ.setdefault("LOCUS_UPLOAD_DIR", tempfile.mkdtemp(prefix="locus-test-uploads-"))

import pytest

from backend.app.database import Base, engine

DB_FILE = "test_locus.db"
UPLOAD_DIR = os.environ["LOCUS_UPLOAD_DIR"]


@pytest.fixture(scope="module", autouse=True)
def reset_database():
    """Give each test module an empty schema.

    Dropping rather than deleting the file keeps every pooled connection valid.
    The app's lifespan handler recreates the tables and reseeds the default
    collections when a module opens its first `TestClient`.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
