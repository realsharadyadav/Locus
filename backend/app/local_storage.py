"""Local disk storage for Secret Images — replaces R2."""

import os
from pathlib import Path

UPLOAD_DIR = Path(__file__).parent.parent / "secret_images"


def configured() -> bool:
    """Always available."""
    return True


def ensure_dir() -> None:
    """Create upload directory if it doesn't exist."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def save_image(filename: str, data: bytes) -> str:
    """Save image to disk. Returns the filename."""
    ensure_dir()
    filepath = UPLOAD_DIR / filename
    filepath.write_bytes(data)
    return filename


def delete_image(filename: str) -> None:
    """Delete image from disk."""
    filepath = UPLOAD_DIR / filename
    if filepath.exists():
        filepath.unlink()


def get_file_path(filename: str) -> Path:
    """Get the full path to a stored image."""
    return UPLOAD_DIR / filename
