"""Run paired source/translation cases in short-lived Docker sandboxes."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.models.schemas import BenchmarkReport, ModelBenchmarkMetrics
from backend.services.compiler_service import DockerSandboxCompiler, OUTPUT_ROOT
from backend.services.translation_service import MODEL_OUTPUT_NAMES
from backend.utils.db import get_migrations_collection

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_CASES_PATH = PROJECT_ROOT / "backend" / "data" / "test_cases.json"
MODEL_NAMES = tuple(MODEL_OUTPUT_NAMES)


class DifferentialSemanticTester:
    """Compare source and target behavior using deterministic stdin/stdout cases."""

    def __init__(self, compiler: DockerSandboxCompiler | None = None) -> None:
        self.compiler = compiler or DockerSandboxCompiler()

    async def run_differential_test(
        self, migration_id: str, test_suite_name: str
    ) -> BenchmarkReport:
        try:
            uuid.UUID(migration_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("migration_id must be a valid UUID") from exc
        migration_dir = (OUTPUT_ROOT / migration_id).resolve()
        try:
            migration_dir.relative_to(OUTPUT_ROOT.resolve())
        except ValueError as exc:
            raise ValueError("Migration directory must be inside outputs/") from exc
        if not migration_dir.is_dir():
            raise FileNotFoundError(f"Migration output directory not found: {migration_dir}")

        suite_data = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))
        cases = suite_data.get(test_suite_name)
        if not isinstance(cases, list) or not cases:
            raise ValueError(f"Unknown or empty test suite: {test_suite_name}")

        collection = get_migrations_collection()
        migration = await collection.find_one({"migration_id": migration_id})
        if migration is None:
            raise ValueError(f"Migration record not found: {migration_id}")
        source_code = migration.get("source_code")
        source_language = self._normalize_language(migration.get("source_language", ""))
        if not isinstance(source_code, str) or not source_code.strip():
            raise ValueError("Migration record does not contain original source_code")

        for index, case in enumerate(cases):
            source_result = await asyncio.to_thread(
                self._run_source_case,
                migration_dir,
                source_code,
                source_language,
                str(case["input"]),
                index,
            )
            if source_result[0] != "SUCCESS":
                raise RuntimeError(
                    f"Original source failed test case {index + 1}: {source_result[1]}"
                )
            if self._normalize_output(source_result[1]) != self._normalize_output(
                str(case["expected_output"])
            ):
                raise ValueError(
                    f"Test case {index + 1} expected_output does not match original source; "
                    "refusing to score translations against an invalid oracle"
                )
        repair_summaries = {
            item.get("model_name"): item
            for item in migration.get("repair_summaries", [])
            if isinstance(item, dict)
        }
        metrics: list[ModelBenchmarkMetrics] = []
        for model_name, artifact_name in MODEL_OUTPUT_NAMES.items():
            target_path = migration_dir / artifact_name
            if not target_path.is_file():
                continue
            target_code = target_path.read_text(encoding="utf-8")
            latencies: list[float] = []
            passed = 0
            final_status = "SUCCESS"
            for index, case in enumerate(cases):
                result = await asyncio.to_thread(
                    self._run_target_case,
                    migration_dir,
                    target_path,
                    target_code,
                    str(case["input"]),
                    index,
                    test_suite_name,
                )
                latencies.append(result.execution_time_seconds)
                if result.status != "SUCCESS":
                    final_status = "FAILED"
                    logger.info(
                        "Target %s failed case %d (%s): %s",
                        model_name,
                        index + 1,
                        result.error_type,
                        result.stderr,
                    )
                elif self._normalize_output(result.stdout) == self._normalize_output(
                    str(case["expected_output"])
                ):
                    passed += 1

            repair = repair_summaries.get(model_name, {})
            repair_attempts = int(repair.get("total_attempts", 0))
            first_pass = (
                bool(repair.get("final_status") == "SUCCESS" and repair_attempts == 0)
                if repair
                else bool(final_status == "SUCCESS" and repair_attempts == 0)
            )
            # A benchmark execution failure supersedes a stale earlier repair result.
            if final_status == "SUCCESS" and repair.get("final_status") == "FAILED":
                final_status = "FAILED"
            sma = (passed / len(cases)) * 100.0
            compile_score = 100.0 if final_status == "SUCCESS" else 0.0
            confidence = 0.30 * compile_score + 0.50 * sma + 0.20 * 100.0
            metrics.append(
                ModelBenchmarkMetrics(
                    model_name=model_name,
                    first_pass_compile=first_pass,
                    repair_attempts_needed=repair_attempts,
                    final_compilation_status=final_status,
                    passed_test_cases=passed,
                    total_test_cases=len(cases),
                    semantic_migration_accuracy=sma,
                    latency_seconds=sum(latencies) / len(latencies),
                    migration_confidence_score=confidence,
                )
            )

        report = BenchmarkReport(
            migration_id=migration_id,
            timestamp=datetime.now(timezone.utc),
            models_evaluated=metrics,
        )
        report_path = migration_dir / "benchmark_report.json"
        report_path.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        update = await collection.update_one(
            {"migration_id": migration_id},
            {"$set": {"benchmark_report": report.model_dump(mode="json")}},
        )
        if update.matched_count == 0:
            raise RuntimeError(f"Migration record disappeared during benchmark: {migration_id}")
        logger.info("Benchmark report saved to %s and persisted to MongoDB", report_path)
        return report

    def _run_target_case(
        self,
        migration_dir: Path,
        target_path: Path,
        target_code: str,
        stdin_text: str,
        case_index: int,
        suite: str,
    ):
        wrapper_text = self._python_case_wrapper(target_code, stdin_text, suite)
        wrapper = migration_dir / f".benchmark_target_{case_index}_{target_path.stem}.py"
        wrapper.write_text(wrapper_text, encoding="utf-8")
        try:
            return self.compiler.compile_and_run_file(str(wrapper), "python", 8)
        finally:
            wrapper.unlink(missing_ok=True)

    def _run_source_case(
        self,
        migration_dir: Path,
        source_code: str,
        language: str,
        stdin_text: str,
        case_index: int,
    ) -> tuple[str, str]:
        if self.compiler.docker_client is None:
            return "FAILED", self.compiler.connection_error or "Docker daemon unavailable"
        if language in {"python", "py"}:
            wrapper = migration_dir / f".benchmark_source_{case_index}.py"
            wrapper.write_text(
                self._python_case_wrapper(source_code, stdin_text, "matrix_multiplication"),
                encoding="utf-8",
            )
            try:
                result = self.compiler.compile_and_run_file(str(wrapper), "python", 8)
                return result.status, result.stdout if result.status == "SUCCESS" else result.stderr
            finally:
                wrapper.unlink(missing_ok=True)
        if language in {"cpp", "c++"}:
            return self._run_cpp_source(migration_dir, source_code, stdin_text, case_index)
        raise ValueError(f"Differential source execution does not support {language!r}")

    def _run_cpp_source(
        self, migration_dir: Path, source_code: str, stdin_text: str, case_index: int
    ) -> tuple[str, str]:
        client = self.compiler.docker_client
        if client is None:
            return "FAILED", self.compiler.connection_error or "Docker daemon unavailable"
        if "int main" not in source_code and "auto main" not in source_code:
            if "#include <iostream>" not in source_code:
                source_code = "#include <iostream>\n" + source_code
            source_code = source_code.rstrip() + "\n" + self._matrix_cpp_main()
        source_file = migration_dir / f".benchmark_source_{case_index}.cpp"
        input_file = migration_dir / f".benchmark_input_{case_index}.txt"
        source_file.write_text(source_code, encoding="utf-8")
        input_file.write_text(stdin_text, encoding="utf-8")
        container = None
        try:
            container = client.containers.run(
                image="gcc:13.5.0-bookworm",
                command=[
                    "/bin/sh", "-c",
                    "g++ -std=c++17 -O2 /app/source.cpp -o /tmp/lexora_program "
                    "&& /tmp/lexora_program < /app/input.txt",
                ],
                volumes={
                    str(source_file.resolve()): {"bind": "/app/source.cpp", "mode": "ro"},
                    str(input_file.resolve()): {"bind": "/app/input.txt", "mode": "ro"},
                },
                network_mode="none",
                mem_limit="512m",
                memswap_limit="512m",
                cpu_period=100000,
                cpu_quota=50000,
                pids_limit=64,
                read_only=True,
                tmpfs={"/tmp": "rw,nosuid,exec,size=32m,mode=1777"},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                user="65534:65534",
                log_config={"type": "json-file", "config": {"max-size": "1m", "max-file": "1"}},
                detach=True,
                remove=False,
            )
            try:
                exit_code = int(container.wait(timeout=8).get("StatusCode", 1))
            except Exception as exc:
                if self.compiler._is_timeout_exception(exc):
                    try:
                        container.kill()
                    except Exception:
                        logger.warning("Unable to kill timed-out C++ benchmark sandbox", exc_info=True)
                    return "FAILED", "Execution timed out after 8 seconds."
                raise
            stdout = self.compiler._decode_logs(container.logs(stdout=True, stderr=False))
            stderr = self.compiler._decode_logs(container.logs(stdout=False, stderr=True))
            return ("SUCCESS", stdout) if exit_code == 0 else ("FAILED", stderr or f"Exit code {exit_code}")
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    logger.exception("Failed to remove C++ benchmark container")
            source_file.unlink(missing_ok=True)
            input_file.unlink(missing_ok=True)

    @staticmethod
    def _python_case_wrapper(source_code: str, stdin_text: str, suite: str) -> str:
        source_literal = repr(source_code)
        input_literal = repr(stdin_text)
        call_matrix = """
_lexora_stream = iter(sys.stdin.read().split())
_lexora_n = int(next(_lexora_stream))
_lexora_a = [[int(next(_lexora_stream)) for _ in range(_lexora_n)] for _ in range(_lexora_n)]
_lexora_b = [[int(next(_lexora_stream)) for _ in range(_lexora_n)] for _ in range(_lexora_n)]
_lexora_result = _lexora_ns['multiply'](_lexora_a, _lexora_b)
for _lexora_row in _lexora_result:
    print(' '.join(map(str, _lexora_row)))
"""
        function_adapter = (
            suite == "matrix_multiplication"
            and re.search(r"^\s*def\s+multiply\s*\(", source_code, re.MULTILINE)
            and "__main__" not in source_code
            and "sys.stdin" not in source_code
            and "input(" not in source_code
        )
        body = call_matrix if function_adapter else ""
        return (
            "import io, sys\n"
            f"sys.stdin = io.StringIO({input_literal})\n"
            f"_lexora_ns = {{'__name__': '__main__'}}\n"
            f"exec(compile({source_literal}, '<benchmark-source>', 'exec'), _lexora_ns)\n"
            + body
        )

    @staticmethod
    def _matrix_cpp_main() -> str:
        return r'''
int main() {
    int n;
    if (!(std::cin >> n)) return 1;
    std::vector<std::vector<int>> a(n, std::vector<int>(n));
    std::vector<std::vector<int>> b(n, std::vector<int>(n));
    for (auto& row : a) for (int& value : row) std::cin >> value;
    for (auto& row : b) for (int& value : row) std::cin >> value;
    auto result = multiply(a, b);
    for (const auto& row : result) {
        for (std::size_t i = 0; i < row.size(); ++i) {
            if (i) std::cout << ' ';
            std::cout << row[i];
        }
        std::cout << '\n';
    }
}
'''

    @staticmethod
    def _normalize_language(language: str) -> str:
        value = language.strip().lower()
        return {"c++": "cpp", "py": "python"}.get(value, value)

    @staticmethod
    def _normalize_output(output: str) -> str:
        return " ".join(output.split())
