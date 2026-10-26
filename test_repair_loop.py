#!/usr/bin/env python3
"""Exercise a real model-guided syntax repair through Docker and MongoDB."""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path

from backend.models.schemas import RepairLoopSummary
from backend.services.compiler_service import DockerSandboxCompiler, OUTPUT_ROOT
from backend.services.repair_loop import AutomatedSelfRepairEngine
from backend.services.translation_service import TranslationOrchestrator
from backend.utils.db import (
    close_mongo_connection,
    connect_to_mongo,
    get_migrations_collection,
)

BROKEN_CODE = "def calculate_sum(a, b) return a + b\n"
SOURCE_CODE = "def calculate_sum(a, b):\n    return a + b\n"
MODEL_NAME = "fine_tuned_hf"
OUTPUT_FILENAME = "fine_tuned_hf_output.py"


async def run_demo() -> int:
    migration_id = str(uuid.uuid4())
    output_directory = OUTPUT_ROOT / migration_id
    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / OUTPUT_FILENAME
    output_path.write_text(BROKEN_CODE, encoding="utf-8")

    compiler = DockerSandboxCompiler()
    collection_ready = False
    print("=" * 70)
    print("LEXORA AUTOMATED SELF-CORRECTION LOOP")
    print("=" * 70)
    print(f"Migration ID             : {migration_id}")
    print(f"Model Under Repair       : {MODEL_NAME}")

    try:
        await connect_to_mongo()
        collection_ready = True
        await get_migrations_collection().insert_one(
            {
                "migration_id": migration_id,
                "name": migration_id,
                "source_code": SOURCE_CODE,
                "source_language": "python",
                "target_language": "python",
                "repair_summaries": [],
            }
        )

        initial = await asyncio.to_thread(
            compiler.compile_and_run_file,
            str(output_path),
            "python",
            5,
        )
        initial_error = (
            initial.stderr.splitlines()[-1] if initial.stderr else initial.error_type
        )
        print(
            "Initial Compilation      : "
            f"{initial.status} ({initial_error})"
        )
        print("-" * 70)

        engine = AutomatedSelfRepairEngine(
            translation_orchestrator=TranslationOrchestrator(),
            compiler=compiler,
        )
        summary: RepairLoopSummary = await engine.repair_model_output(
            migration_id=migration_id,
            model_name=MODEL_NAME,
            source_code=SOURCE_CODE,
            target_lang="python",
        )

        stored_migration = await get_migrations_collection().find_one(
            {"migration_id": migration_id}
        )
        audit_logged = bool(
            stored_migration
            and any(
                item.get("model_name") == MODEL_NAME
                for item in stored_migration.get("repair_summaries", [])
            )
        )
        print("-" * 70)
        print(
            "Final Status             : "
            + (
                f"REPAIRED IN {summary.total_attempts} ATTEMPT"
                if summary.final_status == "SUCCESS" and summary.total_attempts == 1
                else f"{summary.final_status} ({summary.total_attempts} attempts)"
            )
        )
        print(f"Updated File Location    : {output_path.relative_to(OUTPUT_ROOT.parent)}")
        print(f"MongoDB Audit Trail      : {'LOGGED' if audit_logged else 'MISSING'}")
        print("=" * 70)

        corrected_file_matches = (
            bool(summary.attempt_history)
            and summary.attempt_history[-1].corrected_code.strip()
            == output_path.read_text(encoding="utf-8").strip()
        )
        traceback_forwarded = (
            bool(summary.attempt_history)
            and summary.attempt_history[0].error_traceback == initial.stderr
        )
        success = (
            initial.status == "FAILED"
            and initial.error_type == "SyntaxError"
            and summary.final_status == "SUCCESS"
            and 1 <= summary.total_attempts <= AutomatedSelfRepairEngine.MAX_RETRIES
            and corrected_file_matches
            and traceback_forwarded
            and audit_logged
        )
        return 0 if success else 1
    except Exception as exc:
        print(f"[FAIL] Repair loop verification failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if collection_ready:
            await close_mongo_connection()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        return asyncio.run(run_demo())
    except KeyboardInterrupt:
        print("[FAIL] Repair loop interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
