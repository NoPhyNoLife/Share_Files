from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Application(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    status: Literal["pending", "approved", "rejected"] = "pending"
    device_name: str
    owner_name: str
    contact: str
    device_description: str = ""
    note: str = ""
    source_ip: str | None = None
    review_note: str = ""
    device_id: str | None = None


class Device(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    application_id: str
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    name: str
    owner_name: str
    contact: str
    token: str
    token_preview: str
    enabled: bool = True
    last_upload_at: str | None = None
    last_upload_ip: str | None = None


class UploadRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    device_id: str | None = None
    uploader_name: str
    uploader_role: Literal["admin", "device"]
    filename: str
    stored_path: str
    visibility: Literal["admin_only", "public"] = "admin_only"
    content_type: str | None = None
    size_bytes: int
    source_ip: str | None = None
    uploaded_at: str = Field(default_factory=utc_now)
