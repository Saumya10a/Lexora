"""Coordinate AST/RAG context and concurrent local/API code translations."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

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
        return f"""You are Lexora, an expert automated compiler and code translator.
Translate the source faithfully into {target_lang}, preserving behavior and using idiomatic target-language constructs.
Generate ONLY executable target language code. Do not wrap in markdown or prose explanations.

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
        started = time.perf_counter()
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set in the environment")
        async with AsyncOpenAI(api_key=api_key, base_url=GROQ_BASE_URL) as client:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
        translated_code = response.choices[0].message.content or ""
        if not translated_code.strip():
            raise RuntimeError(f"{model_name} returned an empty translation")
        return SingleModelTranslationResult(
            model_name=model_name,
            translated_code=translated_code.strip(),
            execution_time_seconds=time.perf_counter() - started,
            file_path="",
        )

    async def translate_with_local_hf(
        self, prompt: str
    ) -> SingleModelTranslationResult:
        started = time.perf_counter()
        translated_code = await asyncio.to_thread(self._generate_local_sync, prompt)
        if not translated_code.strip():
            raise RuntimeError("fine_tuned_hf returned an empty translation")
        return SingleModelTranslationResult(
            model_name="fine_tuned_hf",
            translated_code=translated_code.strip(),
            execution_time_seconds=time.perf_counter() - started,
            file_path="",
        )

    def _generate_local_sync(self, prompt: str) -> str:
        # Model initialization and generation are blocking; keep them off the event loop.
        with self._local_model_lock:
            if self._local_model is None:
                from backend.services.finetune_service import LocalFineTunedModelInference

                self._local_model = LocalFineTunedModelInference()
            return self._local_model.generate_translation(prompt)

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
        await get_migrations_collection().insert_one(document)
        logger.info("Migration %s completed and stored", migration_id)
        return migration

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
