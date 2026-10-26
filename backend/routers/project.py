"""Repository upload, framework migration, and target archive download APIs."""

from __future__ import annotations

import asyncio
import logging
import json
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from starlette.background import BackgroundTask

from backend.services.graph_orchestrator import MigrationGraph
from backend.services.project_analytics import project_analytics
from backend.services.project_ingester import MAX_ARCHIVE_BYTES, OUTPUT_ROOT, ProjectIngester
from backend.services.structural_mapper import FrameworkStructuralMapper
from backend.services.translation_service import GROQ_MODEL_NAME, TranslationOrchestrator
from backend.utils.db import get_projects_collection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/project", tags=["Project Migration"])


def _build_project_report(
    migration_id: str,
    source_files: list[dict],
    model_results: list[dict],
    target_framework: str,
    project_profile: dict | None = None,
) -> dict:
    code_suffixes = {".java", ".go"}
    report_models = []
    for model in model_results:
        target_root = OUTPUT_ROOT / migration_id / model.get("target_directory", "target")
        expected = [
            row for row in model.get("files", [])
            if row.get("target_path", "").endswith(tuple(code_suffixes))
            and row.get("status") not in {"SKIPPED", "GENERATED_CONFIG", "COPIED_RESOURCE"}
        ]
        translated = [row for row in expected if row.get("status") == "TRANSLATED"]
        checked = valid = nonempty = 0
        parser = None
        if target_framework == "spring-boot":
            try:
                from tree_sitter_languages import get_parser
                parser = get_parser("java")
            except Exception:
                parser = None
        for row in translated:
            target_path = target_root / row["target_path"]
            if not target_path.is_file():
                continue
            code = target_path.read_text(encoding="utf-8", errors="replace")
            if code.strip():
                nonempty += 1
            if parser and target_path.suffix == ".java":
                checked += 1
                if not parser.parse(code.encode("utf-8")).root_node.has_error:
                    valid += 1
        report_models.append({
            "model_name": model.get("model_name"),
            "status": model.get("status", "FAILED"),
            "error": model.get("error"),
            "expected_code_files": len(expected),
            "translated_code_files": len(translated),
            "coverage_percent": round(len(translated) * 100 / len(expected), 1) if expected else 0.0,
            "nonempty_files": nonempty,
            "java_syntax_checked": checked,
            "java_syntax_valid": valid,
            "java_syntax_valid_percent": round(valid * 100 / checked, 1) if checked else None,
            "wall_time_seconds": model.get("wall_time_seconds", 0),
            "assessment": "Artifact coverage and syntax checks only; semantic equivalence requires review and runtime tests.",
        })
    return {
        "migration_id": migration_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_file_count": len(source_files),
        "project_profile": project_profile,
        "target_framework": target_framework,
        "models": report_models,
        "comparison": "Source/target behavior was not executed; this report does not claim semantic equivalence.",
    }


def _render_project_report(report: dict) -> str:
    lines = [
        "# Lexora Migration Quality and Model Comparison", "",
        f"- Migration: `{report['migration_id']}`",
        f"- Source files staged: {report['source_file_count']}",
        f"- Target: {report['target_framework']}",
        f"- Generated: {report['created_at']}", "",
        "| Model | Status | Code files | Coverage | Java syntax | Duration |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for model in report["models"]:
        syntax = (f"{model['java_syntax_valid']}/{model['java_syntax_checked']}"
                  if model["java_syntax_checked"] else "not checked")
        lines.append(
            f"| {model['model_name']} | {model['status']} | "
            f"{model['translated_code_files']}/{model['expected_code_files']} | "
            f"{model['coverage_percent']}% | {syntax} | {model['wall_time_seconds']}s |"
        )
        if model.get("error"):
            lines.extend(["", f"**{model['model_name']} error:** {model['error']}"])
    lines.extend(["", "## Interpretation", "", report["comparison"],
                  "Coverage means a file was generated; syntax validity does not demonstrate correct behavior."])
    profile = report.get("project_profile") or {}
    if profile.get("warning"):
        lines.extend(["", "## Repository scope", "", profile["warning"]])
        platforms = profile.get("data_platforms") or []
        if platforms:
            lines.append("Detected data platforms: " + ", ".join(platforms) + ".")
    return "\n".join(lines) + "\n"


class ProjectMigrationRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    migration_id: str
    target_framework: Literal["spring-boot", "go-fiber"] = "spring-boot"
    model_name: str | None = None
    model_names: list[str] | None = None


@router.post("/upload")
async def upload_project(
    file: UploadFile = File(...),
    target_framework: str = Form("spring-boot"),
) -> dict:
    if not file.filename or Path(file.filename).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="Upload a .zip project archive")
    try:
        framework = FrameworkStructuralMapper.normalize_framework(target_framework)
        archive_bytes = await file.read(MAX_ARCHIVE_BYTES + 1)
        migration_id = str(uuid.uuid4())
        ingested = await asyncio.to_thread(
            ProjectIngester().ingest_zip, archive_bytes, migration_id
        )
        mapper = FrameworkStructuralMapper()
        detected_framework = ingested["detected_framework"]
        project_profile = ingested["project_profile"]
        structural_map = mapper.map_paths(
            ingested["files"], framework, source_type=detected_framework["type"]
        )
        collection = get_projects_collection()
        await collection.update_one(
            {"migration_id": migration_id},
            {"$set": {
                "migration_id": migration_id,
                "name": migration_id,
                "status": "UPLOADED",
                "target_framework": framework,
                "detected_framework": detected_framework,
                "project_profile": project_profile,
                "source_type": detected_framework["type"],
                "source_tree": ingested["source_tree"],
                "structural_map": structural_map["mapping"],
                "target_tree_preview": structural_map["target_tree"],
                "source_root": str(ingested["source_root"]),
                "total_files": len(ingested["files"]),
            }, "$setOnInsert": {"created_at": time.time()}},
            upsert=True,
        )
        return {
            "migration_id": migration_id,
            "detected_framework": detected_framework,
            "project_profile": project_profile,
            "source_type": detected_framework["type"],
            "target_framework": framework,
            "available_targets": mapper.available_targets(detected_framework["type"]),
            "source_tree": ingested["source_tree"],
            "target_tree": structural_map["target_tree"],
            "structural_map": structural_map["mapping"],
            "total_files": len(ingested["files"]),
            "next_step": "POST /api/project/migrate",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Project upload failed")
        raise HTTPException(status_code=500, detail=f"Project upload failed: {type(exc).__name__}") from exc
    finally:
        await file.close()


@router.post("/migrate")
async def migrate_project(request: ProjectMigrationRequest) -> dict:
    try:
        migration_id = str(uuid.UUID(request.migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a UUID") from exc
    migration_root = (OUTPUT_ROOT / migration_id).resolve()
    source_root = (migration_root / "source").resolve()
    if not source_root.is_relative_to(OUTPUT_ROOT.resolve()) or not source_root.is_dir():
        raise HTTPException(status_code=404, detail="Uploaded project was not found")
    try:
        ingester = ProjectIngester()
        files = await asyncio.to_thread(ingester.collect_source_files, source_root)
        if not files:
            raise HTTPException(status_code=400, detail="No supported source files were found")
        collection = get_projects_collection()
        project_record = await collection.find_one({"migration_id": migration_id}) or {}
        detected = project_record.get("detected_framework")
        project_profile = project_record.get("project_profile")
        source_type = (
            detected.get("type") if isinstance(detected, dict) else None
        ) or ProjectIngester.detect_framework(source_root)["type"]
        source_type = FrameworkStructuralMapper.normalize_source_type(source_type)
        supported = {"fine_tuned_hf", GROQ_MODEL_NAME}
        model_names = request.model_names or ([request.model_name] if request.model_name else [GROQ_MODEL_NAME])
        # Keep order stable and prevent duplicate model runs.
        model_names = list(dict.fromkeys(model_names))
        invalid = [name for name in model_names if name not in supported]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Unsupported models: {', '.join(invalid)}")

        await collection.update_one(
            {"migration_id": migration_id},
            {"$set": {"status": "MIGRATING", "model_names": model_names,
                       "source_type": source_type, "target_framework": request.target_framework,
                       "total_files": len(files), "models": {}}},
        )

        model_directories = {GROQ_MODEL_NAME: "target", "fine_tuned_hf": "target-qwen-finetuned"}
        model_keys = {GROQ_MODEL_NAME: "groq", "fine_tuned_hf": "qwen_finetuned"}
        shared_translator = TranslationOrchestrator()

        async def run_model(model_name: str) -> dict:
            model_key = model_keys[model_name]
            target_directory = model_directories[model_name]

            async def persist_progress(progress: dict) -> None:
                await collection.update_one(
                    {"migration_id": migration_id},
                    {"$set": {
                        f"models.{model_key}.current_file": progress["current_file"],
                        f"models.{model_key}.completed_files": progress["completed_files"],
                        f"models.{model_key}.total_files": progress["total_files"],
                        f"models.{model_key}.status": progress["status"],
                    }, "$push": {f"models.{model_key}.progress": progress}},
                )

            started = time.perf_counter()
            try:
                result = await MigrationGraph(translator=shared_translator).migrate_project(
                    migration_id=migration_id,
                    source_root=source_root,
                    files=files,
                    target_framework=request.target_framework,
                    source_type=source_type,
                    model_name=model_name,
                    target_subdirectory=target_directory,
                    # Reuse complete files from an interrupted/previous attempt.
                    # This lets the same migration ID continue without paying
                    # for already completed model calls again.
                    resume_existing=True,
                    continue_on_error=True,
                    progress_callback=persist_progress,
                )
                result["status"] = "COMPLETED" if not any(row.get("status") == "FAILED" for row in result["files"]) else "PARTIAL"
            except Exception as exc:
                logger.exception("Project migration failed for %s", model_name)
                result = {"model_name": model_name, "status": "FAILED", "target_tree": [], "files": [], "error": f"{type(exc).__name__}: {exc}"}
            result["model_name"] = model_name
            result["wall_time_seconds"] = round(time.perf_counter() - started, 2)
            result["target_directory"] = target_directory
            await collection.update_one(
                {"migration_id": migration_id},
                {"$set": {f"models.{model_key}.result": result,
                           f"models.{model_key}.status": result.get("status", "PARTIAL")}},
            )
            return result

        # Each selected model walks the dependency graph independently.
        model_results = await asyncio.gather(*(run_model(name) for name in model_names))
        primary = next((item for item in model_results if item.get("model_name") == GROQ_MODEL_NAME), model_results[0])
        report = _build_project_report(
            migration_id, files, model_results, request.target_framework, project_profile
        )
        report_json = migration_root / "translation_comparison_report.json"
        report_markdown = migration_root / "translation_comparison_report.md"
        migration_root.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report_markdown.write_text(_render_project_report(report), encoding="utf-8")
        result_payload = {
            **primary,
            "model_results": model_results,
            "target_tree": primary.get("target_tree", []),
            "project_profile": project_profile,
            "report_available": True,
        }
        await collection.update_one(
            {"migration_id": migration_id},
            {"$set": {"status": "COMPLETED" if all(row.get("status") == "COMPLETED" for row in model_results) else (
                           "PARTIAL" if any(row.get("status") in {"COMPLETED", "PARTIAL"} for row in model_results) else "FAILED"),
                       "target_tree": result_payload["target_tree"], "model_results": model_results,
                       "translation_report": report, "completed_at": time.time()}},
        )
        return result_payload
    except HTTPException:
        raise
    except ValueError as exc:
        await get_projects_collection().update_one(
            {"migration_id": migration_id}, {"$set": {"status": "FAILED", "error": str(exc)}}
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Project migration %s failed", migration_id)
        await get_projects_collection().update_one(
            {"migration_id": migration_id},
            {"$set": {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}},
        )
        # Include a concise cause in the API response instead of hiding every
        # per-file failure behind the generic RuntimeError label.
        reason = str(exc).strip() or "No additional error details were provided."
        if len(reason) > 600:
            reason = reason[:597] + "..."
        raise HTTPException(
            status_code=502,
            detail=f"Project migration failed ({type(exc).__name__}): {reason}",
        ) from exc


@router.get("/results/{migration_id}")
async def get_project_results(migration_id: str) -> dict:
    try:
        migration_id = str(uuid.UUID(migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a UUID") from exc
    migration_root = (OUTPUT_ROOT / migration_id).resolve()
    if not migration_root.is_relative_to(OUTPUT_ROOT.resolve()) or not migration_root.is_dir():
        raise HTTPException(status_code=404, detail="Migration was not found")
    model_directories = {"groq": "target", "fine_tuned_hf": "target-qwen-finetuned"}
    all_model_directories = {"groq": "target", "fine_tuned_hf": "target-qwen-finetuned"}
    # Include all model outputs that exist on disk so evaluators can inspect both Groq and fine-tuned Qwen
    model_directories = {
        key: directory for key, directory in all_model_directories.items()
        if (migration_root / directory).is_dir()
    }
    outputs: dict[str, dict[str, str]] = {}
    model_results = []
    for model_name, directory in model_directories.items():
        target_root = migration_root / directory
        if not target_root.is_dir():
            continue
        content_by_file: dict[str, str] = {}
        for path in target_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".java", ".go", ".py", ".js", ".ts"}:
                relative = path.relative_to(target_root).as_posix()
                try:
                    content_by_file[relative] = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
        if content_by_file:
            outputs[model_name] = content_by_file
            model_results.append({"model_name": model_name, "status": "AVAILABLE", "target_directory": directory, "file_count": len(content_by_file)})
    return {"migration_id": migration_id, "outputs": outputs, "model_results": model_results}


@router.get("/status/{migration_id}")
async def get_project_status(migration_id: str) -> dict:
    try:
        migration_id = str(uuid.UUID(migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a UUID") from exc
    record = await get_projects_collection().find_one(
        {"migration_id": migration_id},
        {"_id": 0, "status": 1, "models": 1, "total_files": 1, "target_framework": 1},
    )
    if not record:
        raise HTTPException(status_code=404, detail="Migration was not found")
    models = {}
    for key, value in (record.get("models") or {}).items():
        value = value or {}
        result = value.get("result", {})
        models[key] = {
            "status": value.get("status", "PENDING"),
            "current_file": value.get("current_file"),
            "completed_files": value.get("completed_files", 0),
            "total_files": value.get("total_files", record.get("total_files", 0)),
            "error": result.get("error"),
        }
    return {
        "migration_id": migration_id,
        "status": record.get("status", "UNKNOWN"),
        "target_framework": record.get("target_framework"),
        "models": models,
    }


@router.get("/report/{migration_id}")
async def download_project_report(
    migration_id: str,
    format: Literal["markdown", "json", "html"] = Query("markdown"),
) -> FileResponse:
    try:
        migration_id = str(uuid.UUID(migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a UUID") from exc
    migration_root = (OUTPUT_ROOT / migration_id).resolve()
    if not migration_root.is_relative_to(OUTPUT_ROOT.resolve()) or not migration_root.is_dir():
        raise HTTPException(status_code=404, detail="Migration was not found")
    
    ext_map = {"markdown": "md", "json": "json", "html": "html"}
    extension = ext_map.get(format, "md")
    report_path = (migration_root / f"translation_comparison_report.{extension}").resolve()
    
    # If html or markdown report does not exist or is basic, generate high-fidelity data science report
    if format in {"html", "markdown"} and (not report_path.is_file() or report_path.stat().st_size < 300):
        content = project_analytics.generate_datascience_report(migration_id, format_type=format)
        report_path.write_text(content, encoding="utf-8")
        
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="Comparison report is not available yet")
        
    media_types = {
        "md": "text/markdown",
        "json": "application/json",
        "html": "text/html",
    }
    return FileResponse(
        report_path,
        media_type=media_types.get(extension, "text/plain"),
        filename=f"lexora-{migration_id}-report.{extension}",
    )


@router.get("/report-content/{migration_id}")
async def get_project_report_content(
    migration_id: str,
    format: Literal["markdown", "json", "html"] = Query("markdown"),
) -> dict:
    try:
        migration_id = str(uuid.UUID(migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a UUID") from exc
    content = project_analytics.generate_datascience_report(migration_id, format_type=format)
    return {"migration_id": migration_id, "format": format, "content": content}


@router.get("/ast-analysis/{migration_id}")
async def get_ast_analysis(migration_id: str) -> dict:
    try:
        migration_id = str(uuid.UUID(migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a UUID") from exc
    return project_analytics.get_ast_analysis(migration_id)


@router.get("/contract-verification/{migration_id}")
async def get_contract_verification(migration_id: str) -> dict:
    try:
        migration_id = str(uuid.UUID(migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a UUID") from exc
    return project_analytics.get_contract_verification(migration_id)


@router.get("/evaluation-metrics/{migration_id}")
async def get_evaluation_metrics(migration_id: str) -> dict:
    try:
        migration_id = str(uuid.UUID(migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a UUID") from exc
    return project_analytics.get_evaluation_metrics(migration_id)


@router.get("/history")
async def get_migration_history() -> list[dict]:
    return await project_analytics.get_migration_history()


@router.get("/download/{migration_id}")
async def download_project(
    migration_id: str,
    model_name: str | None = Query(None, description="fine_tuned_hf or openai/gpt-oss-20b; omitted downloads the primary target"),
) -> FileResponse:
    try:
        migration_id = str(uuid.UUID(migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a UUID") from exc
    migration_root = (OUTPUT_ROOT / migration_id).resolve()
    model_directories = {
        "fine_tuned_hf": "target-qwen-finetuned",
        "openai/gpt-oss-20b": "target",
        "groq": "target",
    }
    if model_name is not None and model_name not in model_directories:
        raise HTTPException(status_code=400, detail="model_name must be fine_tuned_hf or openai/gpt-oss-20b")
    directory = model_directories.get(model_name, "target")
    target_root = (migration_root / directory).resolve()
    if not target_root.is_relative_to(OUTPUT_ROOT.resolve()) or not target_root.is_dir():
        raise HTTPException(status_code=404, detail="Target project was not found")
    if not any(path.is_file() for path in target_root.rglob("*")):
        raise HTTPException(status_code=404, detail="Target project contains no files")
    archive_path = migration_root / f"{migration_id}-{directory}.zip"
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(target_root.rglob("*")):
                if path.is_file():
                    archive.write(path, Path("target") / path.relative_to(target_root))
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Unable to package target project") from exc
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"lexora-{migration_id}-{directory}.zip",
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )
