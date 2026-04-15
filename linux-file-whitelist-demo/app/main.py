from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=401, detail="Admin login required")


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


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "title": settings.app_name,
            "request_submitted": request.query_params.get("submitted") == "1",
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
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/logout")
async def admin_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request) -> HTMLResponse:
    require_admin(request)
    applications = sorted(store.list_applications(), key=lambda item: item.created_at, reverse=True)
    devices = sorted(store.list_devices(), key=lambda item: item.created_at, reverse=True)
    uploads = sorted(store.list_uploads(), key=lambda item: item.uploaded_at, reverse=True)[:20]
    return templates.TemplateResponse(
        request=request,
        name="admin_dashboard.html",
        context={
            "applications": applications,
            "devices": devices,
            "uploads": uploads,
            "token": request.query_params.get("token"),
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
    return RedirectResponse(url=f"/admin?token={encoded}", status_code=303)


@app.post("/admin/applications/{application_id}/reject")
async def reject_application(
    request: Request,
    application_id: str,
    review_note: str = Form(""),
) -> RedirectResponse:
    require_admin(request)
    store.reject_application(application_id, review_note=review_note.strip())
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/devices/{device_id}/disable")
async def disable_device(request: Request, device_id: str) -> RedirectResponse:
    require_admin(request)
    store.disable_device(device_id)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    token = bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API token")
    device = store.get_device_by_token(token)
    if not device:
        raise HTTPException(status_code=403, detail="Invalid or disabled token")

    payload = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(payload) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.max_upload_mb} MB limit")

    safe_name = Path(file.filename or "upload.bin").name
    device_dir = upload_root / device.id
    device_dir.mkdir(parents=True, exist_ok=True)
    timestamp = utc_now().replace(":", "-")
    target_name = f"{timestamp}__{safe_name}"
    stored_path = device_dir / target_name
    stored_path.write_bytes(payload)

    record = UploadRecord(
        device_id=device.id,
        filename=safe_name,
        stored_path=str(stored_path.relative_to(BASE_DIR)),
        content_type=file.content_type,
        size_bytes=len(payload),
        source_ip=client_ip(request),
    )
    store.record_upload(record)
    return JSONResponse(
        {
            "message": "Upload accepted",
            "device_id": device.id,
            "filename": safe_name,
            "stored_path": record.stored_path,
            "size_bytes": record.size_bytes,
        }
    )


@app.get("/healthz")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
