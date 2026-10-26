#!/usr/bin/env python3
"""Exercise Docker isolation, output capture, error classification and cleanup."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from backend.models.schemas import CompilationResult

OUTPUT_FILES = {
    "fine_tuned_hf": ("Model 1 (Fine-Tuned HF)", "fine_tuned_hf_output.py"),
    "openai/gpt-oss-20b": ("Model 2 (Groq GPT-OSS 20B)", "openai_gpt_oss_20b_output.py"),
}
BROKEN_SOURCE = "def invalid_func( missing_colon\n    return True\n"


def find_migration_folder(output_root: Path) -> Path | None:
    candidates = []
    for directory in output_root.iterdir():
        if not directory.is_dir():
            continue
        try:
            uuid.UUID(directory.name)
        except ValueError:
            continue
        if any((directory / filename).is_file() for _, filename in OUTPUT_FILES.values()):
            candidates.append(directory)
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def print_result(label: str, result: CompilationResult) -> None:
    print(
        f"{label:26}: {result.status} | "
        f"Time: {result.execution_time_seconds:.2f}s"
    )
    print(f"{'Stdout':26}: {result.stdout or 'Clean'}")
    print(f"{'Stderr':26}: {result.stderr or 'Clean'}")
    print(f"{'Error Type':26}: {result.error_type}")
    print("-" * 70)


def main() -> int:
    try:
        from backend.services.compiler_service import DockerSandboxCompiler, OUTPUT_ROOT
    except ModuleNotFoundError as exc:
        print(f"[FAIL] Required dependency is unavailable: {exc.name}")
        return 1

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    print("=" * 70)
    print("LEXORA DOCKER SANDBOX EXECUTION LOGS")
    print("=" * 70)
    compiler = DockerSandboxCompiler()
    migration_folder = find_migration_folder(OUTPUT_ROOT)
    migration_id = migration_folder.name if migration_folder else "UNAVAILABLE"
    print(f"Migration ID             : {migration_id}")
    print("-" * 70)

    results: list[tuple[str, CompilationResult]] = []
    cleanup_checks: list[bool] = []
    if migration_folder is None:
        print("No Phase 4 migration output folder with model artifacts was found.")
    else:
        for model_name, (label, filename) in OUTPUT_FILES.items():
            try:
                result = compiler.compile_and_run_file(
                    str(migration_folder / filename), target_lang="python", timeout_seconds=5
                )
            except (FileNotFoundError, ValueError) as exc:
                result = CompilationResult(
                    migration_id=migration_id,
                    model_name=model_name,
                    status="FAILED",
                    stdout="",
                    stderr=str(exc),
                    execution_time_seconds=0.0,
                    error_type="FileNotFoundError" if isinstance(exc, FileNotFoundError) else "ValueError",
                )
            print_result(label, result)
            results.append((label, result))
            cleanup_checks.append(compiler.last_cleanup_confirmed)

    control_path = OUTPUT_ROOT / "control_test_broken.py"
    control_result: CompilationResult | None = None
    try:
        control_path.write_text(BROKEN_SOURCE, encoding="utf-8")
        control_result = compiler.compile_and_run_file(
            str(control_path), target_lang="python", timeout_seconds=5
        )
        cleanup_checks.append(compiler.last_cleanup_confirmed)
        print_result("Control Test (Broken)", control_result)
        if control_result.error_type == "SyntaxError":
            detail = next(
                (
                    line.split(":", 1)[1].strip()
                    for line in reversed(control_result.stderr.splitlines())
                    if line.startswith("SyntaxError:")
                ),
                "syntax error",
            )
            print(f"{'Error Captured':26}: SyntaxError ({detail})")
    except Exception as exc:
        cleanup_checks.append(False)
        print(f"Control Test (Broken)    : FAILED | {type(exc).__name__}: {exc}")
    finally:
        control_path.unlink(missing_ok=True)

    cleanup_confirmed = bool(cleanup_checks) and all(cleanup_checks)
    print(
        "Container Cleanup Status : "
        f"{'CONFIRMED (Containers destroyed)' if cleanup_confirmed else 'NOT CONFIRMED'}"
    )
    print("=" * 70)

    successful_models = len(results) == len(OUTPUT_FILES) and all(
        result.status == "SUCCESS" for _, result in results
    )
    control_caught = control_result is not None and control_result.error_type == "SyntaxError"
    return 0 if successful_models and control_caught and cleanup_confirmed else 1


if __name__ == "__main__":
    sys.exit(main())
