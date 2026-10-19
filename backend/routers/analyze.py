from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.models.schemas import ASTAnalysisRequest, ASTAnalysisResponse, ErrorResponse
from backend.services.ast_analyzer import ASTAnalyzer, AnalysisSyntaxError

router = APIRouter(tags=["analysis"])
analyzer = ASTAnalyzer()


@router.post(
    "/analyze",
    response_model=ASTAnalysisResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def analyze_code(request: ASTAnalysisRequest) -> ASTAnalysisResponse | JSONResponse:
    try:
        return analyzer.parse_code(request.source_code, request.language)
    except (AnalysisSyntaxError, ValueError) as exc:
        error = ErrorResponse(
            error_code="INVALID_SOURCE",
            message="The source code could not be analyzed.",
            details=str(exc),
        )
        return JSONResponse(status_code=400, content=error.model_dump())
    except Exception:
        error = ErrorResponse(
            error_code="ANALYSIS_FAILED",
            message="An unexpected error occurred during source analysis.",
            details=None,
        )
        return JSONResponse(status_code=500, content=error.model_dump())
