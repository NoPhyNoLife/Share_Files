from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from .models import Application, Device, UploadRecord, utc_now


class JsonStore:
    def __init__(self, data_file: Path):
        self.data_file = data_file
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_file.exists():
            self._write({"applications": [], "devices": [], "uploads": []})

    def _read(self) -> dict[str, Any]:
        with self.data_file.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, payload: dict[str, Any]) -> None:
        tmp_path = self.data_file.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(self.data_file)

    def list_applications(self) -> list[Application]:
        raw = self._read()["applications"]
        return [Application.model_validate(item) for item in raw]

    def list_devices(self) -> list[Device]:
        raw = self._read()["devices"]
        return [Device.model_validate(item) for item in raw]

    def list_uploads(self) -> list[UploadRecord]:
        raw = self._read()["uploads"]
        return [UploadRecord.model_validate(item) for item in raw]

    def create_application(self, application: Application) -> Application:
        data = self._read()
        data["applications"].append(application.model_dump())
        self._write(data)
        return application

    def get_application(self, application_id: str) -> Application | None:
        for item in self.list_applications():
            if item.id == application_id:
                return item
        return None

    def update_application(self, application: Application) -> Application:
        data = self._read()
        applications = []
        for item in data["applications"]:
            if item["id"] == application.id:
                applications.append(application.model_dump())
            else:
                applications.append(item)
        data["applications"] = applications
        self._write(data)
        return application

    def approve_application(self, application_id: str, review_note: str = "") -> Device:
        data = self._read()
        application = None
        for item in data["applications"]:
            if item["id"] == application_id:
                application = Application.model_validate(item)
                break
        if application is None:
            raise KeyError("Application not found")
        if application.status == "approved" and application.device_id:
            device = self.get_device(application.device_id)
            if device is None:
                raise KeyError("Approved device is missing")
            return device

        token = secrets.token_urlsafe(32)
        device = Device(
            application_id=application.id,
            name=application.device_name,
            owner_name=application.owner_name,
            contact=application.contact,
            token=token,
            token_preview=f"{token[:6]}...{token[-4:]}",
        )
        application.status = "approved"
        application.updated_at = utc_now()
        application.review_note = review_note
        application.device_id = device.id

        next_applications = []
        for item in data["applications"]:
            if item["id"] == application.id:
                next_applications.append(application.model_dump())
            else:
                next_applications.append(item)
        data["applications"] = next_applications
        data["devices"].append(device.model_dump())
        self._write(data)
        return device

    def reject_application(self, application_id: str, review_note: str = "") -> Application:
        data = self._read()
        rejected = None
        next_applications = []
        for item in data["applications"]:
            application = Application.model_validate(item)
            if application.id == application_id:
                application.status = "rejected"
                application.updated_at = utc_now()
                application.review_note = review_note
                rejected = application
                next_applications.append(application.model_dump())
            else:
                next_applications.append(item)
        if rejected is None:
            raise KeyError("Application not found")
        data["applications"] = next_applications
        self._write(data)
        return rejected

    def get_device(self, device_id: str) -> Device | None:
        for item in self.list_devices():
            if item.id == device_id:
                return item
        return None

    def get_device_by_token(self, token: str) -> Device | None:
        for item in self.list_devices():
            if item.token == token and item.enabled:
                return item
        return None

    def disable_device(self, device_id: str) -> Device:
        data = self._read()
        target = None
        next_devices = []
        for item in data["devices"]:
            device = Device.model_validate(item)
            if device.id == device_id:
                device.enabled = False
                device.updated_at = utc_now()
                target = device
                next_devices.append(device.model_dump())
            else:
                next_devices.append(item)
        if target is None:
            raise KeyError("Device not found")
        data["devices"] = next_devices
        self._write(data)
        return target

    def record_upload(self, upload: UploadRecord) -> UploadRecord:
        data = self._read()
        next_devices = []
        for item in data["devices"]:
            device = Device.model_validate(item)
            if device.id == upload.device_id:
                device.last_upload_at = upload.uploaded_at
                device.last_upload_ip = upload.source_ip
                device.updated_at = utc_now()
                next_devices.append(device.model_dump())
            else:
                next_devices.append(item)
        data["devices"] = next_devices
        data["uploads"].append(upload.model_dump())
        self._write(data)
        return upload
