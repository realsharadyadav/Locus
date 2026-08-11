"""Secret Images: upload/list/delete with local compression, plus the auth gate.

Images are compressed to 50KB max and stored in backend/secret_images/.
Tests monkeypatch local_storage to stay hermetic.
"""

import io
import os

import pytest

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete

from backend.app import auth as auth_module
from backend.app import local_storage
from backend.app import secret_images
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


class FakeStorage:
    """In-memory storage for testing."""

    def __init__(self):
        self.files: dict[str, bytes] = {}

    def save(self, filename, data):
        self.files[filename] = data
        return filename

    def delete(self, filename):
        self.files.pop(filename, None)

    def get_path(self, filename):
        class FakePath:
            def __init__(self, data):
                self.data = data

            def exists(self):
                return True

            def read_bytes(self):
                return self.data

        return FakePath(self.files.get(filename, b""))


@pytest.fixture()
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(local_storage, "save_image", fake.save)
    monkeypatch.setattr(local_storage, "delete_image", fake.delete)
    monkeypatch.setattr(local_storage, "get_file_path", fake.get_path)
    yield fake
    _clear_secret_images()


def _create_test_image(size=(500, 500), format="PNG", random_noise=False):
    """Create a real test image of specified size."""
    if random_noise:
        import random
        img = Image.new("RGB", size)
        pixels = img.load()
        for i in range(size[0]):
            for j in range(size[1]):
                pixels[i, j] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    else:
        img = Image.new("RGB", size, color="red")
    buffer = io.BytesIO()
    img.save(buffer, format=format)
    return buffer.getvalue()


def test_status_always_configured(client):
    response = client.get("/api/secret-images/status")
    assert response.status_code == 200
    assert response.json() == {"configured": True}


def test_upload_compresses_large_image(client, storage):
    # Create a 1000x1000 PNG with random noise (doesn't compress well)
    large_png = _create_test_image(size=(1000, 1000), format="PNG", random_noise=True)
    assert len(large_png) > 50_000, f"Test image should be larger than 50KB, got {len(large_png)}"

    upload = client.post(
        "/api/secret-images",
        files={"file": ("test.png", large_png, "image/png")},
    )
    assert upload.status_code == 201
    body = upload.json()
    assert body["original_filename"] == "test.png"
    assert body["size_bytes"] <= 50_000, f"Compressed image should be under 50KB, got {body['size_bytes']}"
    assert len(storage.files) == 1


def test_upload_small_image(client, storage):
    small_png = _create_test_image(size=(100, 100), format="PNG")
    upload = client.post(
        "/api/secret-images",
        files={"file": ("small.png", small_png, "image/png")},
    )
    assert upload.status_code == 201
    body = upload.json()
    assert body["original_filename"] == "small.png"
    assert body["content_type"] in ("image/png", "image/jpeg")
    assert len(storage.files) == 1


def test_upload_jpeg(client, storage):
    jpg_data = _create_test_image(size=(500, 500), format="JPEG")
    upload = client.post(
        "/api/secret-images",
        files={"file": ("photo.jpg", jpg_data, "image/jpeg")},
    )
    assert upload.status_code == 201
    body = upload.json()
    assert body["original_filename"] == "photo.jpg"
    assert body["size_bytes"] > 0
    assert len(storage.files) == 1


def test_list_and_delete(client, storage):
    png_data = _create_test_image(size=(200, 200), format="PNG")
    upload = client.post(
        "/api/secret-images",
        files={"file": ("cat.png", png_data, "image/png")},
    )
    assert upload.status_code == 201
    image_id = upload.json()["id"]

    listing = client.get("/api/secret-images")
    assert listing.status_code == 200
    images = listing.json()
    assert len(images) == 1
    assert images[0]["id"] == image_id

    deletion = client.delete(f"/api/secret-images/{image_id}")
    assert deletion.status_code == 204
    assert storage.files == {}
    assert client.get("/api/secret-images").json() == []


def test_non_image_upload_rejected(client, storage):
    response = client.post(
        "/api/secret-images",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert "image" in response.json()["detail"].lower()


def test_empty_file_rejected(client, storage):
    response = client.post(
        "/api/secret-images",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400


def test_list_newest_first(client, storage):
    png_a = _create_test_image(size=(100, 100), format="PNG")
    png_b = _create_test_image(size=(100, 100), format="PNG")

    first = client.post(
        "/api/secret-images",
        files={"file": ("a.png", png_a, "image/png")},
    ).json()
    second = client.post(
        "/api/secret-images",
        files={"file": ("b.png", png_b, "image/png")},
    ).json()
    images = client.get("/api/secret-images").json()
    assert [img["id"] for img in images] == [second["id"], first["id"]]


def test_requires_auth_when_password_set(client, storage, monkeypatch):
    monkeypatch.setenv("LOCUS_AUTH_PASSWORD", PASSWORD)
    response = client.get("/api/secret-images")
    assert response.status_code == 401


def test_phone_sized_photo_is_bounded_not_just_quality_crushed(client, storage):
    """A 12MP photo must come back small *and* downscaled.

    Compression used to sweep quality across the full-resolution image before it
    ever considered resizing, which burned seconds of CPU per upload and left the
    result as a full-size frame crushed to quality 5. Bounding the long edge first
    is what makes the upload fast enough to finish, so assert the bound holds.
    """
    # Noise built from urandom rather than _create_test_image's per-pixel loop:
    # at 12M pixels that loop costs ~16s, which the suite should not pay.
    size = (4032, 3024)
    noise = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    buffer = io.BytesIO()
    noise.save(buffer, format="JPEG", quality=92)
    photo = buffer.getvalue()

    upload = client.post(
        "/api/secret-images",
        files={"file": ("IMG_0001.jpg", photo, "image/jpeg")},
    )
    assert upload.status_code == 201
    assert upload.json()["size_bytes"] <= 50 * 1024

    stored = Image.open(io.BytesIO(next(iter(storage.files.values()))))
    assert max(stored.size) <= secret_images.MAX_EDGE_PX
    # Aspect ratio survives the downscale — 4:3 in, 4:3 out.
    assert abs((stored.width / stored.height) - (4032 / 3024)) < 0.02


def test_exif_orientation_is_applied(client, storage):
    """Re-encoding drops EXIF, so the rotation has to be baked into the pixels.

    Without this the portrait photos that phones store as landscape-plus-a-rotation
    tag would come back on their side.
    """
    portrait = Image.new("RGB", (400, 200), color="red")
    exif = portrait.getexif()
    exif[274] = 6  # Orientation: rotate 90° CW on display
    buffer = io.BytesIO()
    portrait.save(buffer, format="JPEG", exif=exif)

    upload = client.post(
        "/api/secret-images",
        files={"file": ("rotated.jpg", buffer.getvalue(), "image/jpeg")},
    )
    assert upload.status_code == 201

    stored = Image.open(io.BytesIO(next(iter(storage.files.values()))))
    # 400x200 tagged "rotate 90" displays as 200x400.
    assert stored.height > stored.width
