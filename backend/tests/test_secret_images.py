"""Secret Images: upload/list/delete with compression, plus the auth gate.

Images are compressed to 50KB max and stored as bytes on their own row, so these
tests need no filesystem stubbing — the hermetic per-module database is the
storage.
"""

import io
import os

import pytest

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import delete, select

from backend.app import auth as auth_module
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


class StoredImages:
    """Reads the stored bytes back out of the database.

    Stands in for the old in-memory storage stub so the existing assertions keep
    reading naturally, but it now inspects the real storage rather than a fake.
    """

    @property
    def files(self) -> dict[str, bytes]:
        with SessionLocal() as db:
            return {
                image.file_path: image.data
                for image in db.scalars(select(SecretImage)).all()
            }


@pytest.fixture()
def storage():
    yield StoredImages()
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


def test_view_serves_the_stored_bytes(client, storage):
    """Round-trip through the database: what went in is what comes back out."""
    upload = client.post(
        "/api/secret-images",
        files={"file": ("cat.png", _create_test_image(size=(300, 300), format="PNG"), "image/png")},
    ).json()

    response = client.get(f"/api/secret-images/view/{upload['id']}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    # Never cacheable by a shared proxy — these are private photos.
    assert "private" in response.headers.get("cache-control", "")
    assert response.content == next(iter(storage.files.values()))
    assert Image.open(io.BytesIO(response.content)).size == (300, 300)


def test_rows_without_bytes_are_hidden_not_broken(client, storage):
    """Leftovers from the disk-backed version must not render as broken tiles.

    Startup prunes them, but a row can also be left behind by a failed write, so
    listing and viewing both have to hold the line on their own.
    """
    with SessionLocal() as db:
        db.add(SecretImage(data=None, file_path="gone.jpg", content_type="image/jpeg", size_bytes=10))
        db.commit()
        orphan_id = db.scalars(select(SecretImage.id)).one()

    assert client.get("/api/secret-images").json() == []
    assert client.get(f"/api/secret-images/view/{orphan_id}").status_code == 404


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
