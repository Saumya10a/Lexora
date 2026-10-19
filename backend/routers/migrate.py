from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.models.schemas import ErrorResponse, MigrationRequest, MigrationResponse
from backend.services.translation_service import TranslationOrchestrator

router = APIRouter(tags=["migration"])
orchestrator = TranslationOrchestrator()


@router.post(
    "/migrate",
    response_model=MigrationResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def migrate_code(request: MigrationRequest) -> MigrationResponse:
    try:
        return await orchestrator.execute_parallel_migration(request)
    except ValueError as exc:
        error = ErrorResponse(
            error_code="INVALID_MIGRATION_REQUEST",
            message="The migration request is invalid.",
            details=str(exc),
        )
        return JSONResponse(status_code=400, content=error.model_dump())
    except Exception as exc:
        error = ErrorResponse(
            error_code="MIGRATION_FAILED",
            message="The migration could not be completed.",
            details=f"{type(exc).__name__}: {exc}",
        )
        return JSONResponse(status_code=500, content=error.model_dump())
