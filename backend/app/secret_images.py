"""Secret Images — private photo uploads stored in the database.

Each upload is compressed to 50KB max and kept as bytes on its own row, so the
photos survive restarts and redeploys on hosts with an ephemeral filesystem and
are covered by the database's own backups. All uploads are password-gated via
the app's Sign-in Gate middleware.
"""

import asyncio
from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import Response
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import SecretImage
from .schemas import SecretImageRead, SecretImagesStatus

router = APIRouter(prefix="/api/secret-images", tags=["secret-images"])

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_COMPRESSED_BYTES = 50 * 1024
COMPRESSION_QUALITY = 85
# A 50KB budget is never met at phone resolution, so a full-size quality sweep is
# guaranteed wasted work — every pass encodes all 12M pixels only to overshoot.
# Bounding the long edge first makes each pass ~30x cheaper and, at this budget,
# also looks better: fewer pixels carrying more quality each beats a full-size
# image crushed to quality 5.
MAX_EDGE_PX = 1600
MIN_EDGE_PX = 320
QUALITY_FLOOR = 30


def _extension(filename: str, content_type: str) -> str:
    if "." in filename:
        return filename.rsplit(".", 1)[-1].lower()[:10]
    return (content_type.split("/")[-1] or "jpg").lower()[:10]


def _encode(img: Image.Image, quality: int) -> bytes:
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def _compress_image(data: bytes) -> tuple[bytes, str]:
    """Compress image to max 50KB, returning (compressed_data, final_format).

    Blocking and CPU-bound — callers must keep it off the event loop.

    Downscale first, then sweep quality, then downscale again if the budget is
    still missed. The previous order (sweep the full-resolution image through 17
    quality steps before ever resizing) spent seconds of CPU on passes that could
    not have fit, which on a small instance was slow enough to hold the whole
    request open until the client gave up.
    """
    try:
        with Image.open(BytesIO(data)) as opened:
            # EXIF orientation is applied here: dropping it later would silently
            # rotate everyone's phone photos, since we re-encode as bare JPEG.
            img = ImageOps.exif_transpose(opened)
            img = img.convert("RGB")

        img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.Resampling.LANCZOS)

        while True:
            for quality in range(COMPRESSION_QUALITY, QUALITY_FLOOR - 1, -10):
                compressed = _encode(img, quality)
                if len(compressed) <= MAX_COMPRESSED_BYTES:
                    return compressed, "image/jpeg"

            # Still over budget at the quality floor: halve the pixel count and
            # retry rather than degrading quality into mush.
            if max(img.size) <= MIN_EDGE_PX:
                return _encode(img, QUALITY_FLOOR), "image/jpeg"
            img = img.resize(
                (max(1, int(img.width * 0.7)), max(1, int(img.height * 0.7))),
                Image.Resampling.LANCZOS,
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to compress image: {str(e)}")


def _with_url(image: SecretImage) -> SecretImageRead:
    """Convert DB model to response schema."""
    read = SecretImageRead.model_validate(image)
    read.url = f"/api/secret-images/view/{image.id}"
    return read


@router.get("/status", response_model=SecretImagesStatus)
def secret_images_status():
    # Nothing left to configure: storage is the database the app already runs on.
    return SecretImagesStatus(configured=True)


@router.get("", response_model=list[SecretImageRead])
def list_secret_images(db: Session = Depends(get_db)):
    # Columns listed explicitly to leave `data` behind — selecting the whole model
    # would drag every photo's bytes through the connection just to render a
    # listing that shows none of them.
    rows = db.execute(
        select(
            SecretImage.id,
            SecretImage.content_type,
            SecretImage.size_bytes,
            SecretImage.original_filename,
            SecretImage.created_at,
        )
        .where(SecretImage.data.is_not(None))
        .order_by(SecretImage.created_at.desc())
    ).all()
    return [
        SecretImageRead(
            id=row.id,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            original_filename=row.original_filename,
            created_at=row.created_at,
            url=f"/api/secret-images/view/{row.id}",
        )
        for row in rows
    ]


@router.post("", response_model=SecretImageRead, status_code=status.HTTP_201_CREATED)
async def upload_secret_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only image uploads are allowed")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Image is too large")

    # Off the event loop: compressing a phone photo is seconds of pure CPU, and
    # running it inline froze the entire backend for the duration — health checks
    # and every other request included. Verified before the change: a concurrent
    # /api/health went from 10ms to 1.8s on a fast box, and proportionally worse
    # on a small instance, which is what surfaced in the browser as a bare
    # "Failed to fetch" rather than a real error message.
    compressed_data, final_content_type = await asyncio.to_thread(_compress_image, data)

    image = SecretImage(
        data=compressed_data,
        # No file is written any more; the name is kept because the column is
        # unique and indexed, and a stable identifier is still useful in logs.
        file_path=f"{uuid4().hex}.{_extension(file.filename or '', final_content_type)}",
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
    """Serve the image bytes."""
    image = db.get(SecretImage, image_id)
    if image is None or not image.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    return Response(
        content=image.data,
        media_type=image.content_type,
        # Private by definition: never let a shared cache hold a copy. The bytes
        # for a given id never change, so the browser may keep its own.
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_secret_image(image_id: int, db: Session = Depends(get_db)):
    image = db.get(SecretImage, image_id)
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    db.delete(image)
    db.commit()
    return None
