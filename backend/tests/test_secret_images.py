"""Secret Images: upload/list/delete against a fake R2, plus the auth gate.

boto3 and a real R2 bucket are replaced by monkeypatching backend.app.r2_storage's free
functions, the same way test_secret_chat_bridge.py fakes the Telegram transport — so this
suite stays hermetic and never touches the network.
"""

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import delete

from backend.app import auth as auth_module
from backend.app import r2_storage
from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import SecretImage

PASSWORD = "correct horse battery staple"


def _clear_secret_images():
    with SessionLocal() as db:
        db.execute(delete(SecretImage))
        db.commit()


def setup_module():
    _clear_secret_images()


def teardown_module():
    _clear_secret_images()


@pytest.fixture(autouse=True)
def reset_login_throttle():
    auth_module._login_failures.clear()
    yield
    auth_module._login_failures.clear()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


class FakeBucket:
    """Stands in for the R2 bucket: an in-memory dict of key -> bytes."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload(self, key, data, content_type):
        self.objects[key] = data

    def delete(self, key):
        self.objects.pop(key, None)

    def presign(self, key, expires_in=900):
        return f"https://fake-r2.example/{key}?expires_in={expires_in}"


@pytest.fixture()
def bucket(monkeypatch):
    fake = FakeBucket()
    monkeypatch.setattr(r2_storage, "configured", lambda: True)
    monkeypatch.setattr(r2_storage, "upload_object", fake.upload)
    monkeypatch.setattr(r2_storage, "delete_object", fake.delete)
    monkeypatch.setattr(r2_storage, "presigned_url", fake.presign)
    yield fake
    _clear_secret_images()


def test_status_reports_unconfigured_by_default(client, monkeypatch):
    monkeypatch.setattr(r2_storage, "configured", lambda: False)
    response = client.get("/api/secret-images/status")
    assert response.status_code == 200
    assert response.json() == {"configured": False}


def test_upload_then_list_then_delete(client, bucket):
    upload = client.post(
        "/api/secret-images",
        files={"file": ("cat.png", b"fake-image-bytes", "image/png")},
    )
    assert upload.status_code == 201
    body = upload.json()
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(b"fake-image-bytes")
    assert body["url"].startswith("https://fake-r2.example/")
    assert len(bucket.objects) == 1

    listing = client.get("/api/secret-images")
    assert listing.status_code == 200
    images = listing.json()
    assert len(images) == 1
    assert images[0]["id"] == body["id"]

    deletion = client.delete(f"/api/secret-images/{body['id']}")
    assert deletion.status_code == 204
    assert bucket.objects == {}
    assert client.get("/api/secret-images").json() == []


def test_non_image_upload_is_rejected(client, bucket):
    response = client.post(
        "/api/secret-images",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_list_newest_first(client, bucket):
    first = client.post(
        "/api/secret-images", files={"file": ("a.png", b"one", "image/png")}
    ).json()
    second = client.post(
        "/api/secret-images", files={"file": ("b.png", b"two", "image/png")}
    ).json()
    images = client.get("/api/secret-images").json()
    assert [image["id"] for image in images] == [second["id"], first["id"]]


def test_requires_auth_when_password_set(client, bucket, monkeypatch):
    monkeypatch.setenv("LOCUS_AUTH_PASSWORD", PASSWORD)
    response = client.get("/api/secret-images")
    assert response.status_code == 401
