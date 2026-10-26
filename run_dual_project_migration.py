#!/usr/bin/env python3
"""Generate and compare Groq and local Qwen project migrations for a ZIP archive."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.graph_orchestrator import MigrationGraph
from backend.services.project_ingester import OUTPUT_ROOT, ProjectIngester
from backend.services.structural_mapper import FrameworkStructuralMapper
from backend.services.translation_service import GROQ_MODEL_NAME, TranslationOrchestrator

ROOT = Path(__file__).resolve().parent
MODEL_TARGETS = {
    "groq": (GROQ_MODEL_NAME, "target-groq"),
    "qwen_finetuned": ("fine_tuned_hf", "target-qwen-finetuned"),
}
logger = logging.getLogger("lexora.dual_migration")


def _zip_directory(source: Path, destination: Path, extra_files: list[Path] | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, Path(source.name) / path.relative_to(source))
        for path in extra_files or []:
            if path.is_file():
                archive.write(path, path.name)


def _assess_output(
    target_root: Path,
    result: dict[str, Any],
    model_name: str,
    expected_target_paths: set[str],
) -> dict[str, Any]:
    records = result.get("files", [])
    mapped_code_sources = [
        row for row in records
        if row.get("target_path", "").endswith((".java", ".go"))
        and row.get("status") not in {"SKIPPED", "GENERATED_CONFIG", "COPIED_RESOURCE"}
    ]
    if not records:
        # A failed model may have completed several files before it hit a quota.
        # Count those physical outputs so the report reflects partial work.
        mapped_code_sources = [
            {"target_path": path, "status": "TRANSLATED"}
            for path in expected_target_paths
            if path.endswith((".java", ".go"))
        ]
        translated = [
            row for row in mapped_code_sources
            if (target_root / row["target_path"]).is_file()
            and (target_root / row["target_path"]).stat().st_size > 0
        ]
    else:
        translated = [row for row in mapped_code_sources if row.get("status") == "TRANSLATED"]
    nonempty = 0
    syntactically_parsed = 0
    syntax_checked = 0
    try:
        from tree_sitter_languages import get_parser

        java_parser = get_parser("java")
    except Exception:
        java_parser = None

    for row in translated:
        target_path = target_root / row["target_path"]
        if not target_path.is_file():
            continue
        content = target_path.read_text(encoding="utf-8", errors="replace")
        if content.strip():
            nonempty += 1
        if target_path.suffix == ".java" and java_parser is not None:
            syntax_checked += 1
            if not java_parser.parse(content.encode("utf-8")).root_node.has_error:
                syntactically_parsed += 1

    expected = len(mapped_code_sources)
    coverage = (len(translated) / expected * 100) if expected else 0.0
    nonempty_rate = (nonempty / len(translated) * 100) if translated else 0.0
    syntax_rate = (syntactically_parsed / syntax_checked * 100) if syntax_checked else None
    # This score measures migration artifact completeness and parseability only;
    # it is not a claim of behavioral equivalence.
    score_components = [(coverage, 0.55), (nonempty_rate, 0.15)]
    if syntax_rate is not None:
        score_components.append((syntax_rate, 0.30))
    weight = sum(component_weight for _, component_weight in score_components)
    score = sum(value * component_weight for value, component_weight in score_components) / weight if weight else 0.0
    latencies = [float(row.get("latency_seconds", 0.0)) for row in translated]
    return {
        "model_name": model_name,
        "status": result.get("status", "COMPLETED"),
        "mapped_source_code_files": expected,
        "translated_files": len(translated),
        "nonempty_files": nonempty,
        "translation_coverage_percent": round(coverage, 2),
        "java_syntax_checked": syntax_checked,
        "java_syntax_valid": syntactically_parsed,
        "java_syntax_valid_percent": round(syntax_rate, 2) if syntax_rate is not None else None,
        "total_model_latency_seconds": round(sum(latencies), 2),
        "mean_file_latency_seconds": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "artifact_quality_score_percent": round(score, 2),
        "assessment_note": "Heuristic coverage and syntax score; runtime behavior and semantic equivalence were not verified.",
    }


async def _persist_report(migration_id: str, report: dict[str, Any]) -> None:
    try:
        from backend.utils.db import connect_to_mongo, close_mongo_connection, get_projects_collection

        await connect_to_mongo()
        await get_projects_collection().update_one(
            {"migration_id": migration_id},
            {
                "$set": {"dual_model_report": report, "dual_model_status": report["comparison"]["status"]},
                "$setOnInsert": {"migration_id": migration_id, "name": migration_id},
            },
            upsert=True,
        )
        await close_mongo_connection()
        print("MongoDB comparison report : PERSISTED")
    except Exception as exc:
        logger.warning("Could not persist the local comparison report: %s", exc)
        print(f"MongoDB comparison report : NOT PERSISTED ({type(exc).__name__})")


async def run(zip_path: Path, target_framework: str, migration_id: str | None = None) -> Path:
    if not migration_id:
        if not zip_path.is_file():
            raise FileNotFoundError(f"ZIP archive not found: {zip_path}")
        migration_id = str(uuid.uuid4())
        ingested = await asyncio.to_thread(
            ProjectIngester().ingest_zip, zip_path.read_bytes(), migration_id
        )
        source_root = Path(ingested["source_root"])
    else:
        migration_root_existing = OUTPUT_ROOT / migration_id
        source_root = migration_root_existing / "source"
        if not source_root.is_dir():
            raise FileNotFoundError(f"Existing staged source not found: {source_root}")
        ingested = {
            "files": ProjectIngester.collect_source_files(source_root),
            "detected_framework": ProjectIngester.detect_framework(source_root),
        }
    migration_root = OUTPUT_ROOT / migration_id
    files = ingested["files"]
    detected = ingested["detected_framework"]
    framework = FrameworkStructuralMapper.normalize_framework(target_framework)
    structure = FrameworkStructuralMapper().map_paths(files, framework, source_type=detected["type"])
    expected_target_paths = set(structure["mapping"].values())
    print(f"Migration ID: {migration_id}")
    print(f"Detected source: {detected['name']} ({len(files)} text files)")
    print(f"Target framework: {framework}")
    print("Note: this archive is an Expo/React Native application, not a backend service.")
    print("Spring Boot output is a structural code translation, not a replacement mobile UI.\n")

    translator = TranslationOrchestrator()
    model_reports: list[dict[str, Any]] = []
    model_status: dict[str, str] = {}
    for label, (model_name, target_dir_name) in MODEL_TARGETS.items():
        target_root = migration_root / target_dir_name
        print(f"=== Translating with {label} ({model_name}) ===")
        started = time.perf_counter()
        try:
            result = await MigrationGraph(translator=translator).migrate_project(
                migration_id=migration_id,
                source_root=source_root,
                files=files,
                target_framework=framework,
                source_type=detected["type"],
                model_name=model_name,
                target_subdirectory=target_dir_name,
                resume_existing=True,
            )
            result["status"] = "COMPLETED"
            model_status[label] = "COMPLETED"
        except Exception as exc:
            logger.exception("%s project translation failed", label)
            result = {"status": "FAILED", "files": [], "error": f"{type(exc).__name__}: {exc}"}
            model_status[label] = "FAILED"
            # Leave the other model a chance to finish even if Groq is throttled.
            print(f"{label} failed: {type(exc).__name__}: {exc}")
        duration = time.perf_counter() - started
        if target_root.is_dir():
            result.update(_assess_output(target_root, result, model_name, expected_target_paths))
            _zip_directory(target_root, migration_root / f"prop-{label}-spring-boot.zip")
        else:
            result.update({
                "model_name": model_name,
                "mapped_source_code_files": 0,
                "translated_files": 0,
                "translation_coverage_percent": 0,
                "artifact_quality_score_percent": 0,
            })
        result["wall_time_seconds"] = round(duration, 2)
        model_reports.append(result)
        print(
            f"{label}: {model_status[label]} | translated "
            f"{result.get('translated_files', 0)}/{result.get('mapped_source_code_files', 0)} code files | "
            f"quality heuristic {result.get('artifact_quality_score_percent', 0)}%"
        )

    report = {
        "migration_id": migration_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_archive": zip_path.name,
        "detected_source_framework": detected,
        "target_framework": framework,
        "source_file_count": len(files),
        "models": model_reports,
        "comparison": {
            "status": "BOTH_COMPLETED" if all(v == "COMPLETED" for v in model_status.values()) else "PARTIAL",
            "metric_definition": "Artifact score = 55% mapped code-file coverage + 15% nonempty output + 30% Java Tree-sitter syntax validity when available.",
            "semantic_equivalence": "Not measured. No source runtime tests/API contract suite was included in the ZIP.",
            "source_scope_caveat": "Expo/React Native screens are mobile UI code; translating them into Spring Boot server classes cannot preserve the mobile application experience.",
        },
        "artifacts": {
            "groq_zip": "prop-groq-spring-boot.zip",
            "qwen_finetuned_zip": "prop-qwen_finetuned-spring-boot.zip",
            "report_json": "translation_comparison_report.json",
            "report_markdown": "translation_comparison_report.md",
        },
    }
    report_json = migration_root / "translation_comparison_report.json"
    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Lexora Model Comparison",
        "",
        f"- Migration ID: `{migration_id}`",
        f"- Source: {detected['name']} — {zip_path.name}",
        f"- Target: {framework}",
        "- Important scope note: this ZIP is Expo/React Native mobile UI, not a backend service.",
        "- Score is a structural coverage/syntax heuristic; semantic equivalence was not measured.",
        "",
        "| Model | Status | Files translated | Coverage | Java syntax valid | Heuristic score | Wall time |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in model_reports:
        syntax = (
            f"{item.get('java_syntax_valid', 0)}/{item.get('java_syntax_checked', 0)}"
            if item.get("java_syntax_valid_percent") is not None else "not checked"
        )
        lines.append(
            f"| {item['model_name']} | {item.get('status')} | "
            f"{item.get('translated_files', 0)}/{item.get('mapped_source_code_files', 0)} | "
            f"{item.get('translation_coverage_percent', 0)}% | {syntax} | "
            f"{item.get('artifact_quality_score_percent', 0)}% | {item.get('wall_time_seconds', 0)}s |"
        )
    report_md = migration_root / "translation_comparison_report.md"
    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bundle = migration_root / "prop-dual-model-comparison.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in (
            "prop-groq-spring-boot.zip",
            "prop-qwen_finetuned-spring-boot.zip",
            "translation_comparison_report.json",
            "translation_comparison_report.md",
        ):
            path = migration_root / name
            if path.is_file():
                archive.write(path, name)

    await _persist_report(migration_id, report)
    print("\nArtifacts:")
    print(f"  Groq target ZIP       : {migration_root / 'prop-groq-spring-boot.zip'}")
    print(f"  Qwen fine-tuned ZIP   : {migration_root / 'prop-qwen_finetuned-spring-boot.zip'}")
    print(f"  Comparison report     : {report_json}")
    print(f"  Combined bundle       : {bundle}")
    return migration_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", nargs="?", default=r"C:\Users\saumy\OneDrive\Desktop\prop.zip")
    parser.add_argument("--target", default="spring-boot", choices=("spring-boot", "go-fiber"))
    parser.add_argument("--resume-migration-id", help="Resume the staged ZIP and existing model outputs for this migration ID")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    try:
        asyncio.run(run(Path(args.zip_path).resolve(), args.target, args.resume_migration_id))
    except Exception as exc:
        logger.exception("Dual-model migration did not complete")
        print(f"Dual-model migration failed: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
