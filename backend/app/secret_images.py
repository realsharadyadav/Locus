"""Secret Images — private photo uploads to Cloudflare R2.

Unlike Secret Chat, this has no guest/share-link concept: every route here sits
behind the app's own password gate (see auth.PUBLIC_PATHS / GUEST_SECRET_CHAT_ROUTES —
nothing under /api/secret-images is listed in either, so require_auth covers it by
default). The R2 bucket itself is private; every read the frontend gets is a fresh,
short-lived presigned URL rather than a stored, cacheable one.
"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import r2_storage
from .database import get_db
from .models import SecretImage
from .schemas import SecretImageRead, SecretImagesStatus

router = APIRouter(prefix="/api/secret-images", tags=["secret-images"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _extension(filename: str, content_type: str) -> str:
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()[:10]
    return (content_type.split("/")[-1] or "bin").lower()[:10]


def _with_url(image: SecretImage) -> SecretImageRead:
    read = SecretImageRead.model_validate(image)
    read.url = r2_storage.presigned_url(image.r2_key)
    return read


@router.get("/status", response_model=SecretImagesStatus)
def secret_images_status():
    return SecretImagesStatus(configured=r2_storage.configured())


@router.get("", response_model=list[SecretImageRead])
def list_secret_images(db: Session = Depends(get_db)):
    if not r2_storage.configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Secret Images is not configured")
    images = db.scalars(select(SecretImage).order_by(SecretImage.created_at.desc())).all()
    return [_with_url(image) for image in images]


@router.post("", response_model=SecretImageRead, status_code=status.HTTP_201_CREATED)
async def upload_secret_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not r2_storage.configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Secret Images is not configured")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image uploads are allowed")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is too large")

    key = f"{uuid4().hex}.{_extension(file.filename or '', file.content_type)}"
    r2_storage.upload_object(key, data, file.content_type)

    image = SecretImage(
        r2_key=key,
        content_type=file.content_type,
        size_bytes=len(data),
        original_filename=file.filename or "",
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return _with_url(image)


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret_image(image_id: int, db: Session = Depends(get_db)):
    image = db.get(SecretImage, image_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    r2_storage.delete_object(image.r2_key)
    db.delete(image)
    db.commit()
    return None
