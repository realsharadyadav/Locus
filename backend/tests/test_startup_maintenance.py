"""Startup catch-up work must not block the app from serving.

Re-extracting tabular profiles and re-indexing embeddings used to run inline in the lifespan
handler, so a cold start walked every uploaded file before answering anything — which is how
the deployed instance timed out its health check and tripped its memory limit on boot.
"""

from threading import Event, current_thread

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import Collection, StoredFile
import backend.app.main as main_module


def _add_file(name: str, status: str = "pending", chunks: int = 0) -> int:
    with SessionLocal() as db:
        # Files belong to a library; the seeded ones are there once the app has booted.
        store_id = db.scalars(select(Collection.id)).first()
        if store_id is None:
            collection = Collection(title="Startup sweep", description="", color="violet")
            db.add(collection)
            db.commit()
            store_id = collection.id
        stored = StoredFile(
            store_id=store_id,
            name=name,
            stored_name=f"stored-{name}",
            content_type="text/plain",
            size=10,
            extracted_text="hello",
            embedding_status=status,
            embedding_backend="local",
            embedding_model="local-hash-embedding-v1",
            embedding_chunks=chunks,
        )
        db.add(stored)
        db.commit()
        return stored.id


@pytest.fixture(autouse=True)
def clean_files():
    yield
    with SessionLocal() as db:
        db.query(StoredFile).delete()
        db.commit()


def test_sweep_indexes_every_file_that_needs_it(monkeypatch):
    indexed = []
    monkeypatch.setattr(main_module, "_index_stored_file", lambda db, stored: indexed.append(stored.id))

    first = _add_file("one.txt")
    second = _add_file("two.txt")
    _add_file("done.txt", status="embedded", chunks=3)

    main_module._startup_maintenance()

    assert set(indexed) == {first, second}, "pending files should be picked up, embedded ones left alone"


def test_one_broken_file_does_not_stop_the_sweep(monkeypatch):
    first = _add_file("boom.txt")
    second = _add_file("fine.txt")

    def explode_on_first(db, stored):
        if stored.id == first:
            raise RuntimeError("corrupt upload")

    monkeypatch.setattr(main_module, "_index_stored_file", explode_on_first)
    main_module._startup_maintenance()  # must not raise

    indexed = []
    monkeypatch.setattr(main_module, "_index_stored_file", lambda db, stored: indexed.append(stored.id))
    main_module._startup_maintenance()
    assert second in indexed


def test_health_answers_while_the_sweep_is_still_running(monkeypatch):
    """The proof that this is off the boot path: health responds mid-sweep."""
    _add_file("slow.txt")
    release = Event()
    started = Event()
    threads = []

    def blocking_index(db, stored):
        threads.append(current_thread().name)
        started.set()
        release.wait(timeout=10)

    monkeypatch.setattr(main_module, "_index_stored_file", blocking_index)

    with TestClient(app) as client:
        assert started.wait(timeout=10), "the sweep never started"
        # Still blocked inside indexing, yet the app answers.
        assert client.get("/api/health").json() == {"status": "ok"}
        assert not release.is_set()
        release.set()

    assert threads and threads[0] != "MainThread", f"indexing ran on {threads[0]}, not a worker"
