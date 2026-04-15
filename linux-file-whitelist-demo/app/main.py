from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from urllib.parse import quote

from .config import get_settings
from .models import Application, UploadRecord, utc_now
from .store import JsonStore

BASE_DIR = Path(__file__).resolve().parent.parent
settings = get_settings()
store = JsonStore((BASE_DIR / settings.data_file).resolve())
upload_root = (BASE_DIR / settings.upload_dir).resolve()
upload_root.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def current_registered_device(request: Request):
    device_id = request.session.get("registered_device_id")
    if not device_id:
        return None
    return store.get_device(device_id)


def is_registered_user(request: Request) -> bool:
    return current_registered_device(request) is not None


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Admin login required")


def require_registered_user(request: Request):
    device = current_registered_device(request)
    if device is None or not device.enabled:
        request.session.pop("registered_device_id", None)
        raise HTTPException(status_code=401, detail="Registered user login required")
    return device


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    header_token = request.headers.get("x-api-token")
    if header_token:
        return header_token.strip()
    return None


def validate_upload(payload: bytes) -> None:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(payload) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb} MB limit")


def persist_upload(
    *,
    filename: str,
    payload: bytes,
    content_type: str | None,
    source_ip: str | None,
    uploader_name: str,
    uploader_role: Literal["admin", "registered", "device"],
    visibility: Literal["admin_only", "registered", "public"],
    device_id: str | None = None,
) -> UploadRecord:
    safe_name = Path(filename or "upload.bin").name
    owner_dir_name = device_id or "admin"
    target_dir = upload_root / owner_dir_name
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now().replace(":", "-")
    stored_path = target_dir / f"{timestamp}__{safe_name}"
    stored_path.write_bytes(payload)
    record = UploadRecord(
        device_id=device_id,
        uploader_name=uploader_name,
        uploader_role=uploader_role,
        filename=safe_name,
        stored_path=str(stored_path.relative_to(BASE_DIR)),
        visibility=visibility,
        content_type=content_type,
        size_bytes=len(payload),
        source_ip=source_ip,
    )
    store.record_upload(record)
    return record


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    public_uploads = sorted(store.list_public_uploads(), key=lambda item: item.uploaded_at, reverse=True)[:10]
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "title": settings.app_name,
            "request_submitted": request.query_params.get("submitted") == "1",
            "public_uploads": public_uploads,
            "registered_device": current_registered_device(request),
        },
    )


@app.post("/apply")
async def apply(
    request: Request,
    device_name: str = Form(...),
    owner_name: str = Form(...),
    contact: str = Form(...),
    device_description: str = Form(""),
    note: str = Form(""),
) -> RedirectResponse:
    application = Application(
        device_name=device_name.strip(),
        owner_name=owner_name.strip(),
        contact=contact.strip(),
        device_description=device_description.strip(),
        note=note.strip(),
        source_ip=client_ip(request),
    )
    store.create_application(application)
    return RedirectResponse(url="/?submitted=1", status_code=303)


@app.get("/workspace/login", response_class=HTMLResponse)
async def workspace_login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="workspace_login.html",
        context={"error": request.query_params.get("error")},
    )


@app.post("/workspace/login")
async def workspace_login(request: Request, api_token: str = Form(...)) -> RedirectResponse:
    device = store.get_device_by_token(api_token.strip())
    if not device:
        return RedirectResponse(url="/workspace/login?error=1", status_code=303)
    request.session["registered_device_id"] = device.id
    return RedirectResponse(url="/workspace", status_code=303)


@app.post("/workspace/logout")
async def workspace_logout(request: Request) -> RedirectResponse:
    request.session.pop("registered_device_id", None)
    return RedirectResponse(url="/", status_code=303)


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin_login.html",
        context={"error": request.query_params.get("error")},
    )


@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)) -> RedirectResponse:
    if not secrets.compare_digest(password, settings.admin_password):
        return RedirectResponse(url="/admin/login?error=1", status_code=303)
    request.session["is_admin"] = True
    return RedirectResponse(url="/admin/review", status_code=303)


@app.post("/admin/logout")
async def admin_logout(request: Request) -> RedirectResponse:
    request.session.pop("is_admin", None)
    return RedirectResponse(url="/admin/login", status_code=303)


@app.get("/admin")
async def admin_index() -> RedirectResponse:
    return RedirectResponse(url="/admin/review", status_code=303)


@app.get("/workspace", response_class=HTMLResponse)
async def workspace_home(request: Request) -> HTMLResponse:
    device = current_registered_device(request)
    if device is None or not device.enabled:
        request.session.pop("registered_device_id", None)
        return RedirectResponse(url="/workspace/login", status_code=303)
    uploads = sorted(store.list_registered_uploads(), key=lambda item: item.uploaded_at, reverse=True)
    return templates.TemplateResponse(
        request=request,
        name="workspace.html",
        context={
            "registered_device": device,
            "uploads": uploads,
            "upload_success": request.query_params.get("upload") == "1",
        },
    )


@app.post("/workspace/upload")
async def workspace_upload(request: Request, file: UploadFile = File(...)) -> RedirectResponse:
    device = require_registered_user(request)
    payload = await file.read()
    validate_upload(payload)
    persist_upload(
        filename=file.filename or "upload.bin",
        payload=payload,
        content_type=file.content_type,
        source_ip=client_ip(request),
        uploader_name=device.owner_name,
        uploader_role="registered",
        visibility="registered",
        device_id=device.id,
    )
    return RedirectResponse(url="/workspace?upload=1", status_code=303)


@app.get("/admin/review", response_class=HTMLResponse)
async def admin_review_dashboard(request: Request) -> HTMLResponse:
    require_admin(request)
    applications = sorted(store.list_applications(), key=lambda item: item.created_at, reverse=True)
    devices = sorted(store.list_devices(), key=lambda item: item.created_at, reverse=True)
    return templates.TemplateResponse(
        request=request,
        name="admin_review.html",
        context={
            "applications": applications,
            "devices": devices,
            "token": request.query_params.get("token"),
        },
    )


@app.get("/admin/files", response_class=HTMLResponse)
async def admin_files_dashboard(request: Request) -> HTMLResponse:
    require_admin(request)
    uploads = sorted(store.list_uploads(), key=lambda item: item.uploaded_at, reverse=True)
    return templates.TemplateResponse(
        request=request,
        name="admin_files.html",
        context={
            "uploads": uploads,
            "admin_upload_success": request.query_params.get("admin_upload") == "1",
        },
    )


@app.post("/admin/applications/{application_id}/approve")
async def approve_application(
    request: Request,
    application_id: str,
    review_note: str = Form(""),
) -> RedirectResponse:
    require_admin(request)
    device = store.approve_application(application_id, review_note=review_note.strip())
    encoded = quote(device.token, safe="")
    return RedirectResponse(url=f"/admin/review?token={encoded}", status_code=303)


@app.post("/admin/applications/{application_id}/reject")
async def reject_application(
    request: Request,
    application_id: str,
    review_note: str = Form(""),
) -> RedirectResponse:
    require_admin(request)
    store.reject_application(application_id, review_note=review_note.strip())
    return RedirectResponse(url="/admin/review", status_code=303)


@app.post("/admin/devices/{device_id}/disable")
async def disable_device(request: Request, device_id: str) -> RedirectResponse:
    require_admin(request)
    store.disable_device(device_id)
    return RedirectResponse(url="/admin/review", status_code=303)


@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    token = bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API token")
    device = store.get_device_by_token(token)
    if not device:
        raise HTTPException(status_code=403, detail="Invalid or disabled token")

    payload = await file.read()
    validate_upload(payload)
    record = persist_upload(
        filename=file.filename or "upload.bin",
        payload=payload,
        content_type=file.content_type,
        source_ip=client_ip(request),
        uploader_name=device.name,
        uploader_role="device",
        visibility="admin_only",
        device_id=device.id,
    )
    return JSONResponse(
        {
            "message": "Upload accepted",
            "device_id": device.id,
            "filename": record.filename,
            "stored_path": record.stored_path,
            "size_bytes": record.size_bytes,
            "visibility": record.visibility,
        }
    )


@app.post("/admin/upload")
async def admin_upload(
    request: Request,
    visibility: str = Form(...),
    file: UploadFile = File(...),
) -> RedirectResponse:
    require_admin(request)
    if visibility not in {"admin_only", "registered", "public"}:
        raise HTTPException(status_code=400, detail="Invalid visibility")
    payload = await file.read()
    validate_upload(payload)
    persist_upload(
        filename=file.filename or "upload.bin",
        payload=payload,
        content_type=file.content_type,
        source_ip=client_ip(request),
        uploader_name="Administrator",
        uploader_role="admin",
        visibility=visibility,  # type: ignore[arg-type]
    )
    return RedirectResponse(url="/admin/files?admin_upload=1", status_code=303)


@app.post("/admin/files/{upload_id}/visibility")
async def update_file_visibility(
    request: Request,
    upload_id: str,
    visibility: str = Form(...),
) -> RedirectResponse:
    require_admin(request)
    if visibility not in {"admin_only", "registered", "public"}:
        raise HTTPException(status_code=400, detail="Invalid visibility")
    upload = store.get_upload(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    upload.visibility = visibility  # type: ignore[assignment]
    store.update_upload(upload)
    return RedirectResponse(url="/admin/files", status_code=303)


@app.get("/downloads", response_class=HTMLResponse)
async def public_downloads(request: Request) -> HTMLResponse:
    uploads = sorted(store.list_public_uploads(), key=lambda item: item.uploaded_at, reverse=True)
    return templates.TemplateResponse(
        request=request,
        name="downloads.html",
        context={
            "uploads": uploads,
            "registered_device": current_registered_device(request),
            "is_admin": is_admin(request),
        },
    )


@app.get("/files/{upload_id}")
async def download_file(request: Request, upload_id: str) -> FileResponse:
    upload = store.get_upload(upload_id)
    if upload is None:
        raise HTTPException(status_code=404, detail="File not found")
    if upload.visibility == "admin_only" and not is_admin(request):
        raise HTTPException(status_code=401, detail="Admin login required")
    if upload.visibility == "registered" and not (is_admin(request) or is_registered_user(request)):
        raise HTTPException(status_code=401, detail="Registered user login required")
    target = (BASE_DIR / upload.stored_path).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="Stored file missing")
    return FileResponse(path=target, filename=upload.filename, media_type=upload.content_type)


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
