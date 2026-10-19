import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.models.schemas import CompilationRequest, CompilationResult, ErrorResponse
from backend.services.compiler_service import DockerSandboxCompiler, OUTPUT_ROOT
from backend.utils.db import get_migrations_collection

router = APIRouter(tags=["compilation"])
compiler = DockerSandboxCompiler()
OUTPUT_NAMES = {
    "fine_tuned_hf": "fine_tuned_hf_output.py",
    "openai/gpt-oss-20b": "openai_gpt_oss_20b_output.py",
}


@router.post(
    "/compile",
    response_model=CompilationResult,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def compile_translation(request: CompilationRequest) -> CompilationResult:
    filename = OUTPUT_NAMES[request.model_name]
    file_path = (OUTPUT_ROOT / request.migration_id / filename).resolve()
    try:
        file_path.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid migration output path") from exc

    collection = get_migrations_collection()
    migration = await collection.find_one({"migration_id": request.migration_id})
    if migration is None:
        raise HTTPException(status_code=404, detail="Migration record was not found")

    try:
        result = await asyncio.to_thread(
            compiler.compile_and_run_file, str(file_path), "python", 5
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await collection.update_one(
        {"migration_id": request.migration_id},
        {"$push": {"compilation_results": result.model_dump()}},
    )
    return result
