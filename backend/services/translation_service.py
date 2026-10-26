"""Coordinate AST/RAG context and concurrent local/API code translations."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from openai import APIStatusError, AsyncOpenAI, RateLimitError

from backend.models.schemas import (
    MigrationRequest,
    MigrationResponse,
    GROQ_MODEL_NAME,
    SingleModelTranslationResult,
)
from backend.services.ast_analyzer import ASTAnalyzer
from backend.utils.db import get_migrations_collection

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "outputs"
MODEL_OUTPUT_NAMES = {
    "fine_tuned_hf": "fine_tuned_hf_output.py",
    GROQ_MODEL_NAME: "openai_gpt_oss_20b_output.py",
}
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MAX_COMPLETION_TOKENS = int(os.environ.get("GROQ_MAX_COMPLETION_TOKENS", "2048"))
GROQ_REQUEST_INTERVAL_SECONDS = float(os.environ.get("GROQ_REQUEST_INTERVAL_SECONDS", "6"))
_GROQ_REQUEST_LOCK = asyncio.Lock()
_GROQ_LAST_REQUEST_AT = 0.0
_GROQ_QUOTA_BLOCKED_UNTIL = 0.0
LANGUAGE_ALIASES = {
    "c++": "cpp",
    "cpp": "cpp",
    "java": "java",
    "python": "python",
    "py": "python",
}


class TranslationOrchestrator:
    def __init__(self) -> None:
        self.ast_analyzer = ASTAnalyzer()
        self._rag_engine: Any | None = None
        self._rag_lock = threading.Lock()
        self._local_model: Any | None = None
        self._local_model_lock = threading.Lock()
        self._repair_engine: Any | None = None
        self._repair_lock = threading.Lock()

    @staticmethod
    def build_system_prompt(
        ast_metrics: dict[str, Any],
        rag_rules: list[dict[str, Any]],
        source_code: str,
        target_lang: str,
    ) -> str:
        rules_text = "\n".join(
            f"- {rule.get('source_pattern', 'source construct')} -> "
            f"{rule.get('target_pattern', 'target construct')}: "
            f"{rule.get('description', '')}"
            for rule in rag_rules
        ) or "- No specific migration rules were retrieved; use idiomatic target language equivalents."
        execution_guidance = (
            "For a standalone Python program, include an `if __name__ == '__main__':` "
            "block that instantiates the appropriate class and calls its entry method, "
            "or calls the main function. Ensure the translated program produces its "
            "expected observable output.\n\n"
            if target_lang.strip().lower() in {"python", "python 3", "python3"}
            else ""
        )
        return f"""You are Lexora, an expert automated compiler and code translator.
Translate the source faithfully into {target_lang}, preserving behavior and using idiomatic target-language constructs.
Generate ONLY executable target language code. Do not wrap in markdown or prose explanations.
{execution_guidance}

AST Structural Metadata:
- Lines of code: {ast_metrics.get('total_lines_of_code', 'unknown')}
- Cyclomatic complexity: {ast_metrics.get('cyclomatic_complexity', 'unknown')} ({ast_metrics.get('complexity_rating', 'unknown')})
- Function count: {ast_metrics.get('function_count', 'unknown')}

Retrieved RAG Migration Rules:
{rules_text}

Raw Source Code:
```source
{source_code}
```

Return only the complete translated source code in {target_lang}."""

    async def translate_with_api(
        self, prompt: str, model_name: str
    ) -> SingleModelTranslationResult:
        global _GROQ_LAST_REQUEST_AT, _GROQ_QUOTA_BLOCKED_UNTIL
        started = time.perf_counter()
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set in the environment")
        blocked_for = _GROQ_QUOTA_BLOCKED_UNTIL - time.monotonic()
        if blocked_for > 0:
            raise RuntimeError(
                "Groq's token quota is exhausted; skipping API calls for "
                f"another {blocked_for:.0f}s so the migration can continue locally"
            )
        strict_prompt = (
            prompt
            + "\n\nIMPORTANT: This is a source-code translation. Do not call, request, "
            "or emit any tools. Return the complete target file as plain text code only."
        )
        response = None
        translated_code = ""
        last_failure = "empty response"
        async with AsyncOpenAI(
            api_key=api_key,
            base_url=GROQ_BASE_URL,
            # The SDK's implicit 429 retry sequence can wait for several minutes
            # without exposing useful progress. Handle throttling below instead.
            max_retries=0,
        ) as client:
            # Keep requested prompt + completion tokens below the 8K on-demand
            # TPM limit seen on Groq's developer tier. GPT-OSS may still return
            # an empty/truncated result or attempt a tool call, so retry once.
            rate_limit_retries = 0
            for attempt, (token_budget, attempt_prompt) in enumerate(
                (
                    (GROQ_MAX_COMPLETION_TOKENS, prompt),
                    (3_072, strict_prompt),
                ),
                start=1,
            ):
                tool_call_failure = False
                while True:
                    try:
                        async with _GROQ_REQUEST_LOCK:
                            wait_seconds = GROQ_REQUEST_INTERVAL_SECONDS - (
                                time.monotonic() - _GROQ_LAST_REQUEST_AT
                            )
                            if wait_seconds > 0:
                                logger.info("Groq request queue: waiting %.1f seconds", wait_seconds)
                                await asyncio.sleep(wait_seconds)
                            response = await client.chat.completions.create(
                                model=model_name,
                                messages=[{"role": "user", "content": attempt_prompt}],
                                temperature=0,
                                # Keep the requested output budget small enough for
                                # the observed on-demand TPM cap. Older pinned SDK
                                # carries Groq extensions in extra_body.
                                extra_body={
                                    "max_completion_tokens": token_budget,
                                    "reasoning_effort": "low",
                                    "include_reasoning": False,
                                },
                            )
                            _GROQ_LAST_REQUEST_AT = time.monotonic()
                        break
                    except RateLimitError as exc:
                        error_text = str(exc)
                        if re.search(r"tokens\s+per\s+day|\bTPD\b|tokens_per_day", error_text, re.IGNORECASE):
                            delay = self._retry_delay_seconds(error_text)
                            if delay is None:
                                # Avoid repeatedly hitting a known exhausted
                                # daily quota when the provider omits reset time.
                                delay = 3600.0
                            _GROQ_QUOTA_BLOCKED_UNTIL = max(
                                _GROQ_QUOTA_BLOCKED_UNTIL,
                                time.monotonic() + delay,
                            )
                            logger.error(
                                "Groq daily token quota exhausted; suppressing further calls for %.0f seconds",
                                delay,
                            )
                            raise RuntimeError(
                                "Groq daily token quota exhausted; existing files are preserved. "
                                "Retry this migration ID after the provider quota resets."
                            ) from exc
                        rate_limit_retries += 1
                        if rate_limit_retries > 4:
                            raise RuntimeError(
                                f"Groq rate limit persisted after {rate_limit_retries - 1} retries; "
                                "wait for the account quota to reset, then retry the migration"
                            ) from exc
                        retry_after = exc.response.headers.get("retry-after") if exc.response else None
                        try:
                            delay = float(retry_after) if retry_after else self._retry_delay_seconds(error_text)
                            if delay is None:
                                delay = min(60, 5 * (2 ** (rate_limit_retries - 1)))
                        except (TypeError, ValueError):
                            delay = min(60, 5 * (2 ** (rate_limit_retries - 1)))
                        delay = max(1.0, min(delay, 300.0))
                        logger.warning(
                            "Groq rate limited %s (retry %d/4); retrying in %.1f seconds",
                            model_name, rate_limit_retries, delay,
                        )
                        await asyncio.sleep(delay)
                    except APIStatusError as exc:
                        # Groq may report TPM overages as HTTP 413 (rather than
                        # HTTP 429). Their response includes the requested token
                        # count; lower completion allowance and retry the same file.
                        error_text = str(exc).lower()
                        if (
                            exc.status_code == 413
                            and "rate_limit_exceeded" in error_text
                            and token_budget > 512
                        ):
                            token_budget = max(512, token_budget // 2)
                            logger.warning(
                                "Groq rejected token budget for %s; retrying with max_completion_tokens=%d",
                                model_name, token_budget,
                            )
                            continue
                        raise
                    except Exception as exc:
                        # Groq reports malformed GPT-OSS tool emissions as HTTP 400.
                        # Retry once with the strict no-tools instruction.
                        error_text = str(exc).lower()
                        if attempt == 1 and any(
                            marker in error_text
                            for marker in ("tool_use_failed", "model called a tool", "tool choice is none")
                        ):
                            last_failure = "model attempted a tool call instead of returning source code"
                            logger.warning("%s attempted a tool call; retrying as plain-code output", model_name)
                            tool_call_failure = True
                            break
                        raise
                if tool_call_failure:
                    continue

                if not response.choices:
                    last_failure = "provider returned no choices"
                    continue
                choice = response.choices[0]
                translated_code = choice.message.content or ""
                if translated_code.strip() and choice.finish_reason != "length":
                    break
                last_failure = (
                    "completion was truncated" if choice.finish_reason == "length"
                    else "provider returned an empty translation"
                )
                logger.warning(
                    "%s returned an empty or truncated result (attempt %d, finish=%s, tokens=%s)",
                    model_name,
                    attempt,
                    choice.finish_reason,
                    getattr(getattr(response, "usage", None), "completion_tokens", None),
                )
        if not translated_code.strip() or (
            response and response.choices and response.choices[0].finish_reason == "length"
        ):
            raise RuntimeError(f"{model_name} failed to return complete code: {last_failure}")
        return SingleModelTranslationResult(
            model_name=model_name,
            translated_code=translated_code.strip(),
            execution_time_seconds=time.perf_counter() - started,
            file_path="",
        )

    async def translate_with_local_hf(
        self, prompt: str, target_path: str = ""
    ) -> SingleModelTranslationResult:
        started = time.perf_counter()
        translated_code = await asyncio.to_thread(self._generate_local_sync, prompt, target_path)
        if not translated_code.strip():
            raise RuntimeError("fine_tuned_hf returned an empty translation")
        return SingleModelTranslationResult(
            model_name="fine_tuned_hf",
            translated_code=translated_code.strip(),
            execution_time_seconds=time.perf_counter() - started,
            file_path="",
        )

    @staticmethod
    def _retry_delay_seconds(message: str) -> float | None:
        """Extract provider text such as 'try again in 18m54.4s' into seconds."""
        match = re.search(
            r"try again in\s*"
            r"(?:(\d+(?:\.\d+)?)\s*h(?:ours?)?\s*)?"
            r"(?:(\d+(?:\.\d+)?)\s*m(?:in(?:utes?)?)?\s*)?"
            r"(?:(\d+(?:\.\d+)?)\s*s(?:ec(?:onds?)?)?)?",
            message,
            re.IGNORECASE,
        )
        if not match or not any(match.groups()):
            return None
        hours, minutes, seconds = (float(value or 0) for value in match.groups())
        return hours * 3600 + minutes * 60 + seconds

    def _generate_local_sync(self, prompt: str, target_path: str = "") -> str:
        # Model initialization and generation are blocking; keep them off the event loop.
        with self._local_model_lock:
            if self._local_model is None:
                from backend.services.finetune_service import LocalFineTunedModelInference

                self._local_model = LocalFineTunedModelInference()
            return self._local_model.generate_translation(prompt, target_path=target_path)

    async def execute_parallel_migration(
        self, request: MigrationRequest
    ) -> MigrationResponse:
        migration_id = str(uuid.uuid4())
        source_key = request.source_language.strip().lower()
        source_lang = LANGUAGE_ALIASES.get(source_key)
        if source_lang is None:
            raise ValueError(f"Unsupported source language: {request.source_language}")
        if not request.target_language.strip():
            raise ValueError("target_language must not be empty")

        ast_result = await asyncio.to_thread(
            self.ast_analyzer.parse_code, request.source_code, source_lang
        )
        metrics = ast_result.metrics.model_dump()

        rag_rules = await asyncio.to_thread(
            self._retrieve_rag_rules_sync,
            ast_result.ast_tree_string,
            source_lang,
            request.target_language.strip().lower(),
        )
        prompt = self.build_system_prompt(
            metrics, rag_rules, request.source_code, request.target_language
        )

        selected = list(dict.fromkeys(request.selected_models))
        unsupported = set(selected) - set(MODEL_OUTPUT_NAMES)
        if unsupported:
            raise ValueError(f"Unsupported model selection(s): {', '.join(sorted(unsupported))}")
        if not selected:
            raise ValueError("At least one model must be selected")

        tasks = []
        for model_name in selected:
            if model_name == "fine_tuned_hf":
                tasks.append(self.translate_with_local_hf(prompt))
            else:
                tasks.append(self.translate_with_api(prompt, model_name))
        results = await asyncio.gather(*tasks)

        output_directory = OUTPUT_ROOT / migration_id
        output_directory.mkdir(parents=True, exist_ok=True)
        completed: list[SingleModelTranslationResult] = []
        for result in results:
            filename = MODEL_OUTPUT_NAMES[result.model_name]
            output_path = output_directory / filename
            await asyncio.to_thread(
                output_path.write_text, result.translated_code, encoding="utf-8"
            )
            completed.append(
                result.model_copy(
                    update={"file_path": str(output_path.relative_to(PROJECT_ROOT))}
                )
            )

        migration = MigrationResponse(
            migration_id=migration_id,
            source_language=request.source_language,
            target_language=request.target_language,
            ast_metrics=metrics,
            applied_rag_rules=rag_rules,
            results=completed,
        )
        document = migration.model_dump()
        # The existing migrations collection has a unique index on `name`.
        document["name"] = migration_id
        document["selected_models"] = selected
        document["source_code"] = request.source_code
        document["created_at"] = time.time()
        document["repair_summaries"] = []
        collection = get_migrations_collection()
        await collection.insert_one(document)

        repair_engine = self._get_repair_engine()
        repair_summaries = await asyncio.gather(
            *(
                repair_engine.repair_model_output(
                    migration_id=migration_id,
                    model_name=result.model_name,
                    source_code=request.source_code,
                    target_lang=request.target_language,
                )
                for result in completed
            )
        )
        # Return the on-disk code after any repair so the response matches the
        # artifacts and MongoDB audit record.
        completed = [
            result.model_copy(
                update={
                    "translated_code": await asyncio.to_thread(
                        (PROJECT_ROOT / result.file_path).read_text, encoding="utf-8"
                    )
                }
            )
            for result in completed
        ]
        migration = migration.model_copy(
            update={"results": completed, "repair_summaries": repair_summaries}
        )
        await collection.update_one(
            {"migration_id": migration_id},
            {
                "$set": {
                    "results": [result.model_dump() for result in completed],
                    "repair_summaries": [summary.model_dump(mode="json") for summary in repair_summaries],
                }
            },
        )
        logger.info("Migration %s completed and stored", migration_id)
        return migration

    def _get_repair_engine(self) -> Any:
        with self._repair_lock:
            if self._repair_engine is None:
                from backend.services.repair_loop import AutomatedSelfRepairEngine

                self._repair_engine = AutomatedSelfRepairEngine(
                    translation_orchestrator=self
                )
            return self._repair_engine

    def _retrieve_rag_rules_sync(
        self, context: str, source_lang: str, target_lang: str
    ) -> list[dict[str, Any]]:
        with self._rag_lock:
            if self._rag_engine is None:
                from backend.services.rag_service import RAGMigrationEngine

                self._rag_engine = RAGMigrationEngine()
            self._rag_engine.seed_rules_if_empty()
            return self._rag_engine.retrieve_migration_rules(
                context, source_lang, target_lang, top_k=3
            )
