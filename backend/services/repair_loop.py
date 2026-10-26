"""Compile generated translations and retry model-guided repairs when needed."""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from backend.models.schemas import (
    GROQ_MODEL_NAME,
    RepairAttemptLog,
    RepairLoopSummary,
)
from backend.services.compiler_service import DockerSandboxCompiler, OUTPUT_ROOT
from backend.utils.db import get_migrations_collection

logger = logging.getLogger(__name__)
MAX_RETRIES = 3

MODEL_OUTPUT_NAMES = {
    "fine_tuned_hf": "fine_tuned_hf_output.py",
    GROQ_MODEL_NAME: "openai_gpt_oss_20b_output.py",
}


class AutomatedSelfRepairEngine:
    """Repair invalid Python translations using the model that produced them."""

    MAX_RETRIES = MAX_RETRIES

    def __init__(
        self,
        translation_orchestrator: Any | None = None,
        compiler: DockerSandboxCompiler | None = None,
    ) -> None:
        self.translation_orchestrator = translation_orchestrator
        self.compiler = compiler or DockerSandboxCompiler()
        self._orchestrator_lock = threading.Lock()

    @staticmethod
    def build_repair_prompt(
        original_source: str,
        current_target_code: str,
        error_stderr: str,
        target_lang: str,
    ) -> str:
        execution_guidance = ""
        if "SilentExecutionError" in error_stderr or "CRITICAL: The script compiled but produced absolutely no output" in error_stderr:
            execution_guidance = (
                "\nExecution-specific correction: the module ran without emitting output. "
                "Add an `if __name__ == '__main__':` block that instantiates the appropriate "
                "class and invokes its entry method (or calls the main function), so the "
                "translated program actually executes.\n"
            )
        return (
            "The translated target language code failed compilation.\n"
            f"Error Traceback: {error_stderr}\n"
            f"Current Broken Code: {current_target_code}\n"
            f"Original Source Code: {original_source}\n"
            f"{execution_guidance}"
            "Task: Fix the compilation/runtime error while preserving original "
            f"functionality in {target_lang}. Return ONLY valid target executable "
            "code. Do not include markdown formatting or explanations."
        )

    async def repair_model_output(
        self,
        migration_id: str,
        model_name: str,
        source_code: str,
        target_lang: str,
    ) -> RepairLoopSummary:
        """Compile once, then perform at most MAX_RETRIES targeted repairs."""
        try:
            uuid.UUID(migration_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("migration_id must be a valid UUID") from exc

        filename = MODEL_OUTPUT_NAMES.get(model_name)
        if filename is None:
            raise ValueError(f"Unsupported repair model: {model_name}")

        output_path = (OUTPUT_ROOT / migration_id / filename).resolve()
        try:
            output_path.relative_to(OUTPUT_ROOT.resolve())
        except ValueError as exc:
            raise ValueError("Repair file must be located inside outputs/") from exc
        if not output_path.is_file():
            raise FileNotFoundError(f"Translation output does not exist: {output_path}")

        if target_lang.strip().lower() != "python":
            summary = RepairLoopSummary(
                model_name=model_name,
                final_status="FAILED",
                total_attempts=0,
                attempt_history=[],
            )
            await self._persist_summary(migration_id, summary)
            return summary

        logger.info("Compiling initial %s output for migration %s", model_name, migration_id)
        compilation = await self._compile(output_path, target_lang)
        history: list[RepairAttemptLog] = []
        if compilation.status == "SUCCESS":
            summary = RepairLoopSummary(
                model_name=model_name,
                final_status="SUCCESS",
                total_attempts=0,
                attempt_history=history,
            )
            await self._persist_summary(migration_id, summary)
            return summary

        logger.info(
            "Initial compilation failed for %s: %s", model_name, compilation.error_type
        )
        # An unavailable Docker daemon or a Docker API failure is infrastructure
        # trouble, not a source-code defect. Avoid spending model calls on it.
        if compilation.error_type in {"DockerUnavailable", "DockerError"}:
            summary = RepairLoopSummary(
                model_name=model_name,
                final_status="FAILED",
                total_attempts=0,
                attempt_history=history,
            )
            await self._persist_summary(migration_id, summary)
            return summary

        for attempt_number in range(1, self.MAX_RETRIES + 1):
            current_code = await asyncio.to_thread(
                output_path.read_text, encoding="utf-8"
            )
            error_traceback = compilation.stderr or compilation.error_type
            prompt = self.build_repair_prompt(
                original_source=source_code,
                current_target_code=current_code,
                error_stderr=error_traceback,
                target_lang=target_lang,
            )
            logger.info(
                "[REPAIR ATTEMPT %d/%d] Prompt constructed -> Querying %s...",
                attempt_number,
                self.MAX_RETRIES,
                model_name,
            )

            try:
                translated = await self._query_repair_model(prompt, model_name)
                corrected_code = self._strip_markdown_fence(translated).strip()
                if not corrected_code:
                    raise RuntimeError("Repair model returned empty code")
            except Exception as exc:
                logger.exception("Repair model call failed on attempt %d", attempt_number)
                history.append(
                    RepairAttemptLog(
                        attempt_number=attempt_number,
                        model_name=model_name,
                        error_traceback=error_traceback,
                        corrected_code="",
                        compilation_status=f"REPAIR_GENERATION_FAILED: {type(exc).__name__}",
                    )
                )
                break

            await asyncio.to_thread(output_path.write_text, corrected_code, encoding="utf-8")
            logger.info(
                "[REPAIR ATTEMPT %d/%d] File overwritten -> Re-compiling in Docker...",
                attempt_number,
                self.MAX_RETRIES,
            )
            compilation = await self._compile(output_path, target_lang)
            history.append(
                RepairAttemptLog(
                    attempt_number=attempt_number,
                    model_name=model_name,
                    error_traceback=error_traceback,
                    corrected_code=corrected_code,
                    compilation_status=compilation.status,
                )
            )
            logger.info(
                "[REPAIR ATTEMPT %d/%d] Result: %s (%0.2fs)",
                attempt_number,
                self.MAX_RETRIES,
                compilation.status,
                compilation.execution_time_seconds,
            )
            if compilation.status == "SUCCESS":
                break
            if compilation.error_type in {"DockerUnavailable", "DockerError"}:
                break

        summary = RepairLoopSummary(
            model_name=model_name,
            final_status=compilation.status,
            total_attempts=len(history),
            attempt_history=history,
        )
        await self._persist_summary(migration_id, summary)
        return summary

    async def _compile(self, output_path: Path, target_lang: str):
        return await asyncio.to_thread(
            self.compiler.compile_and_run_file,
            str(output_path),
            target_lang,
            5,
        )

    async def _query_repair_model(self, prompt: str, model_name: str) -> str:
        orchestrator = self._get_translation_orchestrator()
        if model_name == "fine_tuned_hf":
            result = await orchestrator.translate_with_local_hf(prompt)
        elif model_name == GROQ_MODEL_NAME:
            result = await orchestrator.translate_with_api(prompt, model_name)
        else:
            raise ValueError(f"Unsupported repair model: {model_name}")
        return result.translated_code

    def _get_translation_orchestrator(self) -> Any:
        if self.translation_orchestrator is None:
            with self._orchestrator_lock:
                if self.translation_orchestrator is None:
                    # Local import avoids a module cycle: TranslationOrchestrator
                    # creates this engine as part of the post-translation flow.
                    from backend.services.translation_service import TranslationOrchestrator

                    self.translation_orchestrator = TranslationOrchestrator()
        return self.translation_orchestrator

    async def _persist_summary(
        self, migration_id: str, summary: RepairLoopSummary
    ) -> None:
        result = await get_migrations_collection().update_one(
            {"migration_id": migration_id},
            {"$push": {"repair_summaries": summary.model_dump(mode="json")}},
        )
        if result.matched_count == 0:
            raise RuntimeError(f"Migration record not found: {migration_id}")

    @staticmethod
    def _strip_markdown_fence(code: str) -> str:
        stripped = code.strip()
        if not stripped.startswith("```"):
            return stripped
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
