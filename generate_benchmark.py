"""Generate a differential behavior report for the newest migration."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from backend.services.compiler_service import OUTPUT_ROOT
from backend.services.semantic_tester import DifferentialSemanticTester
from backend.services.translation_service import MODEL_OUTPUT_NAMES
from backend.utils.db import close_mongo_connection, connect_to_mongo


def find_migration_id() -> str:
    candidates = []
    for folder in OUTPUT_ROOT.iterdir():
        if not folder.is_dir():
            continue
        try:
            uuid.UUID(folder.name)
        except ValueError:
            continue
        if any((folder / name).is_file() for name in MODEL_OUTPUT_NAMES.values()):
            candidates.append(folder)
    if not candidates:
        raise FileNotFoundError("No migration output folder with model artifacts was found in outputs/")
    return max(candidates, key=lambda item: item.stat().st_mtime).name


def display_name(model_name: str) -> str:
    return "FINE-TUNED HF MODEL" if model_name == "fine_tuned_hf" else "GROQ / API MODEL"


def render_report(report, mongo_status: str) -> None:
    columns = {item.model_name: item for item in report.models_evaluated}
    model_names = list(columns)
    left = model_names[0] if model_names else "fine_tuned_hf"
    right = model_names[1] if len(model_names) > 1 else (model_names[0] if model_names else "")

    def cell(model: str, formatter) -> str:
        item = columns.get(model)
        return formatter(item) if item else "NOT FOUND"

    print("=" * 70)
    print("LEXORA EMPIRICAL MODEL BENCHMARK REPORT")
    print("=" * 70)
    print(f"Migration ID: {report.migration_id}")
    print("-" * 70)
    print(f"{'METRIC':<31} | {display_name(left):^18} | {display_name(right):^18}")
    print("-" * 70)
    rows = [
        ("First-Pass Compilation", lambda m: "SUCCESS" if m.first_pass_compile else "FAILED"),
        ("Repair Attempts Required", lambda m: f"{m.repair_attempts_needed} Attempt" + ("s" if m.repair_attempts_needed != 1 else "")),
        ("Final Compilation Status", lambda m: m.final_compilation_status),
        ("Semantic Migration Accuracy", lambda m: f"{m.semantic_migration_accuracy:.1f}% ({m.passed_test_cases}/{m.total_test_cases})"),
        ("Average Latency", lambda m: f"{m.latency_seconds:.2f}s"),
        ("MIGRATION CONFIDENCE SCORE", lambda m: f"{m.migration_confidence_score:.1f}%"),
    ]
    for label, formatter in rows:
        print(f"{label:<31} | {cell(left, formatter):^18} | {cell(right, formatter):^18}")
    print("=" * 70)
    print(f"Benchmark JSON Written to     : outputs/{report.migration_id}/benchmark_report.json")
    print(f"MongoDB Persistence Status    : {mongo_status}")
    print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration_id", nargs="?", help="UUID of a migration in outputs/")
    parser.add_argument("--suite", default="matrix_multiplication", help="Test suite key in backend/data/test_cases.json")
    args = parser.parse_args()

    try:
        migration_id = args.migration_id or find_migration_id()
        report = asyncio.run(run_benchmark(migration_id, args.suite))
        render_report(report, "UPDATED")
        return 0
    except Exception as exc:
        print(f"[FAIL] Benchmark generation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


async def run_benchmark(migration_id: str, suite_name: str):
    await connect_to_mongo()
    try:
        return await DifferentialSemanticTester().run_differential_test(
            migration_id, suite_name
        )
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    raise SystemExit(main())
