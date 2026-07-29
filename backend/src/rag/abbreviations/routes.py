"""Public administration and worker-facing import routes for abbreviations."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from uuid import UUID

from rag.auth.dependencies import require_csrf, require_current_user
from rag.auth.identity_models import UserRecord
from rag.internal.service_token_auth import require_service_token
from rag.shared.contracts.http import ErrorResponse

from .models import (
    AbbreviationEntryRecord,
    AbbreviationGlossaryRecord,
    AbbreviationSourceRecord,
)
from .schemas import (
    AbbreviationEntry,
    AbbreviationEntryCreateRequest,
    AbbreviationEntryUpdateRequest,
    AbbreviationGlossary,
    AbbreviationGlossaryResponse,
    AbbreviationImportRequest,
    AbbreviationImportResponse,
    AbbreviationSource,
)
from .service import AbbreviationGlossaryRejected, AbbreviationGlossaryService
from .dependencies import get_abbreviation_service

router = APIRouter(prefix="/abbreviation-glossaries", tags=["abbreviation-glossaries"])
internal_router = APIRouter(
    prefix="/abbreviation-glossaries",
    tags=["internal-abbreviation-glossaries"],
    dependencies=[Depends(require_service_token)],
)

_STATUS_BY_CATEGORY = {
    "forbidden": status.HTTP_403_FORBIDDEN,
    "not_found": status.HTTP_404_NOT_FOUND,
    "invalid": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "conflict": status.HTTP_409_CONFLICT,
}


@router.get(
    "",
    response_model=AbbreviationGlossaryResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
    summary="View the global abbreviation glossary",
)
async def get_abbreviation_glossary(
    user: UserRecord = Depends(require_current_user),
    service: AbbreviationGlossaryService = Depends(get_abbreviation_service),
) -> AbbreviationGlossaryResponse:
    glossary, sources, entries = _result(lambda: service.view(actor=user))
    return AbbreviationGlossaryResponse(
        glossary=_glossary_schema(glossary) if glossary else None,
        sources=[_source_schema(source) for source in sources],
        items=[_entry_schema(entry) for entry in entries],
    )


@router.post(
    "/entries",
    response_model=AbbreviationEntry,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
    summary="Add an abbreviation entry",
)
async def create_abbreviation_entry(
    payload: AbbreviationEntryCreateRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: AbbreviationGlossaryService = Depends(get_abbreviation_service),
) -> AbbreviationEntry:
    require_csrf(request)
    entry = _result(
        lambda: service.create_entry(
            abbreviation=payload.abbreviation,
            expansion=payload.expansion,
            actor=user,
        )
    )
    return _entry_schema(entry)


@router.patch(
    "/entries/{entry_id}",
    response_model=AbbreviationEntry,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
    summary="Edit an abbreviation entry",
)
async def update_abbreviation_entry(
    entry_id: UUID,
    payload: AbbreviationEntryUpdateRequest,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: AbbreviationGlossaryService = Depends(get_abbreviation_service),
) -> AbbreviationEntry:
    require_csrf(request)
    entry = _result(
        lambda: service.update_entry(
            str(entry_id),
            abbreviation=payload.abbreviation,
            expansion=payload.expansion,
            expected_revision=payload.expected_revision,
            actor=user,
        )
    )
    return _entry_schema(entry)


@router.delete(
    "/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
    summary="Delete an abbreviation entry",
)
async def delete_abbreviation_entry(
    entry_id: UUID,
    request: Request,
    expected_revision: int = Query(ge=1),
    user: UserRecord = Depends(require_current_user),
    service: AbbreviationGlossaryService = Depends(get_abbreviation_service),
) -> Response:
    require_csrf(request)
    _result(
        lambda: service.delete_entry(
            str(entry_id),
            expected_revision=expected_revision,
            actor=user,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/sources/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    summary="Remove an abbreviation PDF source",
)
async def remove_abbreviation_source(
    document_id: UUID,
    request: Request,
    user: UserRecord = Depends(require_current_user),
    service: AbbreviationGlossaryService = Depends(get_abbreviation_service),
) -> Response:
    require_csrf(request)
    _result(lambda: service.remove_source(str(document_id), actor=user))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@internal_router.post(
    "/import",
    response_model=AbbreviationImportResponse,
    summary="Replace managed entries from an ingested glossary document",
)
async def import_abbreviation_glossary(
    payload: AbbreviationImportRequest,
    service: AbbreviationGlossaryService = Depends(get_abbreviation_service),
) -> AbbreviationImportResponse:
    imported_count = _result(
        lambda: service.import_document_entries(
            document_id=str(payload.document_id),
            entries=[
                (entry.abbreviation, entry.expansion, entry.source_page)
                for entry in payload.entries
            ],
        )
    )
    return AbbreviationImportResponse(imported_count=imported_count)


def _result(action):
    try:
        return action()
    except AbbreviationGlossaryRejected as exc:
        raise HTTPException(
            status_code=_STATUS_BY_CATEGORY[exc.category],
            detail={"code": exc.code, "message": exc.message},
        ) from exc


def _entry_schema(entry: AbbreviationEntryRecord) -> AbbreviationEntry:
    return AbbreviationEntry(
        id=entry.id,
        abbreviation=entry.abbreviation,
        expansion=entry.expansion,
        source_kind=entry.source_kind,
        source_document_id=entry.source_document_id,
        source_document_title=entry.source_document_title,
        source_page=entry.source_page,
        source_count=entry.source_count,
        revision=entry.revision,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _glossary_schema(glossary: AbbreviationGlossaryRecord) -> AbbreviationGlossary:
    return AbbreviationGlossary(
        source_document_id=glossary.source_document_id,
        source_document_title=glossary.source_document_title,
        updated_at=glossary.updated_at,
    )


def _source_schema(source: AbbreviationSourceRecord) -> AbbreviationSource:
    return AbbreviationSource(
        document_id=source.document_id,
        document_title=source.document_title,
        entry_count=source.entry_count,
        activated_at=source.activated_at,
    )
