from functools import lru_cache
from pathlib import Path
import os

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Whitelist Upload Demo"
    admin_password: str = os.getenv("ADMIN_PASSWORD", "change-me")
    session_secret: str = os.getenv("SESSION_SECRET", "dev-session-secret")
    data_file: Path = Path(os.getenv("DATA_FILE", "data/db.json"))
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", "uploads"))
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "50"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
