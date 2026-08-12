"""Legacy on-disk location for Secret Images.

Photos now live in the database (see `secret_images.py`). This module survives
only so the one-time migration can find files written by the disk-backed version
and pull them into their rows; nothing else reads or writes here. Once every
deployment has started at least once on the new schema it can be deleted along
with the directory.
"""

from pathlib import Path

UPLOAD_DIR = Path(__file__).parent.parent / "secret_images"


def get_file_path(filename: str) -> Path:
    """Path a pre-migration row's `file_path` would have pointed at."""
    return UPLOAD_DIR / filename
