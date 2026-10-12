"""Public read and Platform Admin management routes for workspace branding."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from rag.auth.dependencies import require_platform_admin_user
from rag.auth.identity_models import UserRecord
from rag.documents.repository import DocumentRepository, get_document_repository
from rag.shared.contracts.http import ErrorResponse

from .dependencies import get_branding_repository
from .models import BrandingRecord, BrandingRepository, DEFAULT_APP_NAME, DEFAULT_PRIMARY_COLOR
from .schemas import BrandingResponse, BrandingUpdateRequest

router = APIRouter(tags=["branding"])
MAX_LOGO_BYTES = 1_000_000
LOGO_CONTENT_TYPES = {"image/png", "image/jpeg"}


@router.get("/branding", response_model=BrandingResponse, summary="Get public workspace branding")
def get_branding(repo: BrandingRepository = Depends(get_branding_repository)) -> BrandingResponse:
    return _response(repo.get_active())


@router.get("/branding/logo", responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}}, summary="Get workspace logo")
def get_logo(repo: BrandingRepository = Depends(get_branding_repository)) -> Response:
    record = repo.get_active()
    if record is None or record.logo_content is None or record.logo_content_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "logo_not_found", "message": "No custom workspace logo is configured."})
    return StreamingResponse(iter([record.logo_content]), media_type=record.logo_content_type, headers={"Cache-Control": "no-cache"})


@router.put("/admin/branding", response_model=BrandingResponse, summary="Update workspace branding")
def update_branding(
    payload: BrandingUpdateRequest,
    user: UserRecord = Depends(require_platform_admin_user),
    repo: BrandingRepository = Depends(get_branding_repository),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> BrandingResponse:
    current = repo.get_active() or BrandingRecord()
    saved = repo.save_active(BrandingRecord(
        app_name=payload.app_name.strip(), primary_color=payload.primary_color.upper(), accent_color=payload.accent_color.upper(), background_color=payload.background_color.upper(),
        login_message=payload.login_message.strip(), support_url=str(payload.support_url) if payload.support_url else None,
        theme_mode=payload.theme_mode, h1_size=payload.h1_size, h1_weight=payload.h1_weight, h1_color=payload.h1_color.upper() if payload.h1_color else None, h2_size=payload.h2_size, h2_weight=payload.h2_weight, h2_color=payload.h2_color.upper() if payload.h2_color else None, body_size=payload.body_size,
        logo_content=current.logo_content, logo_content_type=current.logo_content_type, updated_by=user.id,
    ))
    audit_repo.append_audit_event(event_type="admin.branding.updated", actor_id=user.id, target_type="workspace", target_id="branding", payload={"app_name": saved.app_name, "primary_color": saved.primary_color, "accent_color": saved.accent_color, "background_color": saved.background_color, "theme_mode": saved.theme_mode, "h1_size": saved.h1_size, "h1_color": saved.h1_color, "h2_size": saved.h2_size, "h2_color": saved.h2_color, "body_size": saved.body_size, "has_logo": saved.logo_content is not None})
    return _response(saved)


@router.post("/admin/branding/logo", response_model=BrandingResponse, summary="Upload workspace logo")
async def upload_logo(
    file: UploadFile = File(...),
    user: UserRecord = Depends(require_platform_admin_user),
    repo: BrandingRepository = Depends(get_branding_repository),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> BrandingResponse:
    content_type = (file.content_type or "").lower()
    content = await file.read(MAX_LOGO_BYTES + 1)
    if content_type not in LOGO_CONTENT_TYPES or len(content) > MAX_LOGO_BYTES or not _is_valid_logo(content, content_type):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": "invalid_logo", "message": "Logo must be a PNG or JPEG no larger than 1 MB."})
    current = repo.get_active() or BrandingRecord()
    saved = repo.save_active(BrandingRecord(app_name=current.app_name, primary_color=current.primary_color, accent_color=current.accent_color, background_color=current.background_color, login_message=current.login_message, support_url=current.support_url, theme_mode=current.theme_mode, h1_size=current.h1_size, h1_weight=current.h1_weight, h1_color=current.h1_color, h2_size=current.h2_size, h2_weight=current.h2_weight, h2_color=current.h2_color, body_size=current.body_size, logo_content=content, logo_content_type=content_type, updated_by=user.id))
    audit_repo.append_audit_event(event_type="admin.branding.logo_uploaded", actor_id=user.id, target_type="workspace", target_id="branding", payload={"content_type": content_type, "size_bytes": len(content)})
    return _response(saved)


@router.delete("/admin/branding/logo", response_model=BrandingResponse, summary="Remove custom workspace logo")
def delete_logo(
    user: UserRecord = Depends(require_platform_admin_user),
    repo: BrandingRepository = Depends(get_branding_repository),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> BrandingResponse:
    current = repo.get_active() or BrandingRecord()
    saved = repo.save_active(BrandingRecord(app_name=current.app_name, primary_color=current.primary_color, accent_color=current.accent_color, background_color=current.background_color, login_message=current.login_message, support_url=current.support_url, theme_mode=current.theme_mode, h1_size=current.h1_size, h1_weight=current.h1_weight, h1_color=current.h1_color, h2_size=current.h2_size, h2_weight=current.h2_weight, h2_color=current.h2_color, body_size=current.body_size, updated_by=user.id))
    audit_repo.append_audit_event(event_type="admin.branding.logo_removed", actor_id=user.id, target_type="workspace", target_id="branding", payload={})
    return _response(saved)


@router.delete("/admin/branding", response_model=BrandingResponse, summary="Restore default workspace branding")
def reset_branding(
    user: UserRecord = Depends(require_platform_admin_user),
    repo: BrandingRepository = Depends(get_branding_repository),
    audit_repo: DocumentRepository = Depends(get_document_repository),
) -> BrandingResponse:
    repo.delete_active()
    audit_repo.append_audit_event(event_type="admin.branding.reset", actor_id=user.id, target_type="workspace", target_id="branding", payload={})
    return _response(None)


def _response(record: BrandingRecord | None) -> BrandingResponse:
    active = record or BrandingRecord(app_name=DEFAULT_APP_NAME, primary_color=DEFAULT_PRIMARY_COLOR)
    return BrandingResponse(app_name=active.app_name, primary_color=active.primary_color, accent_color=active.accent_color, background_color=active.background_color, login_message=active.login_message, support_url=active.support_url, theme_mode=active.theme_mode, h1_size=active.h1_size, h1_weight=active.h1_weight, h1_color=active.h1_color, h2_size=active.h2_size, h2_weight=active.h2_weight, h2_color=active.h2_color, body_size=active.body_size, logo_url="/api/v1/branding/logo" if active.logo_content else None, updated_at=active.updated_at)


def _is_valid_logo(content: bytes, content_type: str) -> bool:
    try:
        from PIL import Image
        from io import BytesIO

        with Image.open(BytesIO(content)) as image:
            image.verify()
            return image.format in ({"PNG"} if content_type == "image/png" else {"JPEG"})
    except (ImportError, OSError, ValueError):
        return False
