import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import ENV_PATH  # Loads the project .env before configuration is read.


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = BACKEND_DIR / "locus.db"
LEGACY_DB = BACKEND_DIR / "mindmap.db"


def _resolve_database_url() -> str:
    configured = os.getenv("LOCUS_DATABASE_URL") or os.getenv("MINDMAP_DATABASE_URL")
    if configured:
        return configured
    db_path = DEFAULT_DB if DEFAULT_DB.exists() or not LEGACY_DB.exists() else LEGACY_DB
    return f"sqlite:///{db_path}"


DATABASE_URL = _resolve_database_url()

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
