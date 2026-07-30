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
"""

import os

os.environ.setdefault("LOCUS_DATABASE_URL", "sqlite:///./test_locus.db")

import pytest

from backend.app.database import Base, engine

DB_FILE = "test_locus.db"


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
