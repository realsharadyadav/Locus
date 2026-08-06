"""Secret Images — private photo uploads saved to local disk.

Stored in backend/secret_images/ with automatic compression to 50KB max.
All uploads are password-gated via the app's Sign-in Gate middleware.
"""

from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import local_storage
from .database import get_db
from .models import SecretImage
from .schemas import SecretImageRead, SecretImagesStatus

router = APIRouter(prefix="/api/secret-images", tags=["secret-images"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_COMPRESSED_BYTES = 50 * 1024
COMPRESSION_QUALITY = 85


def _extension(filename: str, content_type: str) -> str:
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()[:10]
    return (content_type.split("/")[-1] or "jpg").lower()[:10]


def _compress_image(data: bytes) -> tuple[bytes, str]:
    """Compress image to max 50KB, returning (compressed_data, final_format)."""
    try:
        img = Image.open(BytesIO(data))
        img = img.convert("RGB")

        quality = COMPRESSION_QUALITY
        while quality > 5:
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            compressed = buffer.getvalue()
            if len(compressed) <= MAX_COMPRESSED_BYTES:
                return compressed, "image/jpeg"
            quality -= 5

        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=5)
        compressed = buffer.getvalue()
        if len(compressed) <= MAX_COMPRESSED_BYTES:
            return compressed, "image/jpeg"

        max_width = img.width
        while max_width > 100 and len(compressed) > MAX_COMPRESSED_BYTES:
            max_width = int(max_width * 0.8)
            scale_factor = max_width / img.width
            new_size = (int(img.width * scale_factor), int(img.height * scale_factor))
            scaled_img = img.resize(new_size, Image.Resampling.LANCZOS)
            buffer = BytesIO()
            scaled_img.save(buffer, format="JPEG", quality=5, optimize=True)
            compressed = buffer.getvalue()

        return compressed, "image/jpeg"
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to compress image: {str(e)}")


def _with_url(image: SecretImage) -> SecretImageRead:
    """Convert DB model to response schema."""
    read = SecretImageRead.model_validate(image)
    read.url = f"/api/secret-images/view/{image.id}"
    return read


@router.get("/status", response_model=SecretImagesStatus)
def secret_images_status():
    return SecretImagesStatus(configured=local_storage.configured())


@router.get("", response_model=list[SecretImageRead])
def list_secret_images(db: Session = Depends(get_db)):
    images = db.scalars(select(SecretImage).order_by(SecretImage.created_at.desc())).all()
    return [_with_url(image) for image in images]


@router.post("", response_model=SecretImageRead, status_code=status.HTTP_201_CREATED)
async def upload_secret_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image uploads are allowed")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is too large")

    compressed_data, final_content_type = _compress_image(data)

    filename = f"{uuid4().hex}.{_extension(file.filename or '', final_content_type)}"
    local_storage.save_image(filename, compressed_data)

    image = SecretImage(
        file_path=filename,
        content_type=final_content_type,
        size_bytes=len(compressed_data),
        original_filename=file.filename or "",
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return _with_url(image)


@router.get("/view/{image_id}")
def view_secret_image(image_id: int, db: Session = Depends(get_db)):
    """Serve the image file."""
    image = db.get(SecretImage, image_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    filepath = local_storage.get_file_path(image.file_path)
    if not filepath.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image file not found")

    from fastapi.responses import FileResponse
    return FileResponse(filepath, media_type=image.content_type)


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret_image(image_id: int, db: Session = Depends(get_db)):
    image = db.get(SecretImage, image_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    local_storage.delete_image(image.file_path)
    db.delete(image)
    db.commit()
    return None
