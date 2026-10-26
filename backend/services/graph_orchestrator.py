"""Dependency-aware translation of a repository into a target framework."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

import networkx as nx

from backend.services.dependency_translator import DependencyTranslator
from backend.services.structural_mapper import FrameworkStructuralMapper
from backend.services.translation_service import GROQ_MODEL_NAME, TranslationOrchestrator

logger = logging.getLogger(__name__)


class MigrationGraph:
    LAYER_ORDER = {"entity": 0, "repository": 1, "service": 2, "controller": 3, "other": 4}
    MODEL_NAMES = {"fine_tuned_hf", GROQ_MODEL_NAME}

    def __init__(self, translator: TranslationOrchestrator | None = None) -> None:
        self.translator = translator or TranslationOrchestrator()
        self.mapper = FrameworkStructuralMapper()
        self.dependency_translator = DependencyTranslator()

    def build_dependency_graph(self, files: list[dict[str, str]]) -> nx.DiGraph:
        graph = nx.DiGraph()
        by_stem: dict[str, list[str]] = {}
        for item in files:
            path = item["path"]
            graph.add_node(path, layer=self._layer(path))
            by_stem.setdefault(Path(path).stem.lower(), []).append(path)
        for item in files:
            source_path, content = item["path"], item["content"]
            for token in self._import_tokens(content):
                candidates = by_stem.get(Path(token).stem.lower(), [])
                for dependency in candidates:
                    if dependency != source_path:
                        graph.add_edge(dependency, source_path)
        # Enforce the requested architecture order, while preserving direct import edges.
        groups: dict[int, list[str]] = {}
        for node, data in graph.nodes(data=True):
            groups.setdefault(self.LAYER_ORDER[data["layer"]], []).append(node)
        active_layers = sorted(groups)
        for left, right in zip(active_layers, active_layers[1:]):
            for predecessor in groups[left]:
                for dependent in groups[right]:
                    graph.add_edge(predecessor, dependent)
        if not nx.is_directed_acyclic_graph(graph):
            # Import cycles are common in legacy code. Remove only the edges that
            # violate the prescribed layer order, then use stable path order.
            cyclic = list(nx.find_cycle(graph))
            for start, end in cyclic:
                if self.LAYER_ORDER[graph.nodes[start]["layer"]] > self.LAYER_ORDER[graph.nodes[end]["layer"]]:
                    graph.remove_edge(start, end)
            if not nx.is_directed_acyclic_graph(graph):
                graph = nx.DiGraph()
                graph.add_nodes_from((item["path"], {"layer": self._layer(item["path"])}) for item in files)
                for left, right in zip(active_layers, active_layers[1:]):
                    for predecessor in groups[left]:
                        for dependent in groups[right]:
                            graph.add_edge(predecessor, dependent)
        return graph

    async def migrate_project(
        self,
        *,
        migration_id: str,
        source_root: Path,
        files: list[dict[str, str]],
        target_framework: str,
        source_type: str = "unknown",
        model_name: str = GROQ_MODEL_NAME,
        target_subdirectory: str = "target",
        resume_existing: bool = False,
        continue_on_error: bool = False,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        if model_name not in self.MODEL_NAMES:
            raise ValueError(f"Unsupported model '{model_name}'")
        target_framework = self.mapper.normalize_framework(target_framework)
        structure = self.mapper.map_paths(files, target_framework, source_type=source_type)
        mapping: dict[str, str] = structure["mapping"]
        if Path(target_subdirectory).name != target_subdirectory or target_subdirectory in {"", ".", ".."}:
            raise ValueError("target_subdirectory must be a single safe directory name")
        output_root = source_root.parent / target_subdirectory
        output_root.mkdir(parents=True, exist_ok=True)

        dependency_result = self.dependency_translator.translate(source_root, output_root, target_framework)
        self._write_scaffold(output_root, target_framework, dependency_result)

        graph = self.build_dependency_graph(files)
        ordered_paths = list(
            nx.lexicographical_topological_sort(
                graph,
                key=lambda node: (self.LAYER_ORDER[graph.nodes[node]["layer"]], node.lower()),
            )
        )
        file_by_path = {item["path"]: item for item in files}
        translated_context: dict[str, str] = {}
        completed: list[dict[str, Any]] = []
        for index, source_path in enumerate(ordered_paths, start=1):
            item = file_by_path[source_path]
            target_path = mapping.get(source_path)
            if not target_path:
                completed.append({"source_path": source_path, "status": "SKIPPED", "reason": "manifest or unsupported file"})
                continue
            target_file = (output_root / target_path).resolve()
            if not target_file.is_relative_to(output_root.resolve()):
                raise ValueError(f"Mapped target path escaped output directory: {target_path}")
            if resume_existing and target_file.is_file() and target_file.stat().st_size > 0:
                generated = target_file.read_text(encoding="utf-8", errors="replace")
                translated_context[source_path] = generated
                completed.append({
                    "source_path": source_path,
                    "target_path": target_path,
                    "model_name": model_name,
                    "latency_seconds": 0.0,
                    "status": "TRANSLATED",
                    "resumed": True,
                })
                if progress_callback:
                    await progress_callback({
                        "migration_id": migration_id,
                        "current_file": source_path,
                        "target_file": target_path,
                        "completed_files": index,
                        "total_files": len(ordered_paths),
                        "status": "RESUMED",
                    })
                continue
            source_content = self._redact_sensitive_content(source_path, item["content"])
            if Path(source_path).name.lower() in {".env", ".env.example"}:
                self._write_env_template(output_root, target_framework, source_content)
                completed.append({"source_path": source_path, "target_path": target_path, "status": "GENERATED_CONFIG"})
                continue
            # Direct copy for preserved frontend files, data pipelines, configs, scripts, tests, and documentation:
            is_preserved = (
                target_path.startswith(("docs/", "frontend/", "pipeline/", "scripts/", "data/", "tests/"))
                or (target_path.startswith(("src/main/resources/", "config/")) and Path(source_path).suffix.lower() not in {".java", ".go"})
                or not target_path.endswith((".java", ".go"))
            )
            if is_preserved:
                target_file = (output_root / target_path).resolve()
                if not target_file.is_relative_to(output_root.resolve()):
                    raise ValueError(f"Mapped target path escaped output directory: {target_path}")
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(source_content, encoding="utf-8")
                completed.append({
                    "source_path": source_path,
                    "target_path": target_path,
                    "status": "COPIED_RESOURCE",
                    "reason": "Preserved asset (frontend, pipeline, script, test, or documentation)",
                })
                continue
            context_parts = []
            context_budget = 800 if model_name == "fine_tuned_hf" else 2400
            for parent in sorted(graph.predecessors(source_path)):
                generated = translated_context.get(parent)
                if generated:
                    header = f"Previously translated {mapping.get(parent, parent)}:\n"
                    remaining = context_budget - sum(len(part) for part in context_parts)
                    if remaining <= len(header):
                        break
                    context_parts.append(header + generated[: remaining - len(header)])
            previous_context = "\n\n".join(context_parts) or "No dependent target files have been translated yet."
            prompt = self._build_file_prompt(
                source_path=source_path,
                target_path=target_path,
                source_code=source_content,
                target_framework=target_framework,
                dependency_info=dependency_result,
                previous_context=previous_context,
            )
            if progress_callback:
                await progress_callback({
                    "migration_id": migration_id,
                    "current_file": source_path,
                    "target_file": target_path,
                    "completed_files": index - 1,
                    "total_files": len(ordered_paths),
                    "status": "TRANSLATING",
                })
            try:
                if model_name == "fine_tuned_hf":
                    result = await self.translator.translate_with_local_hf(prompt, target_path=target_path)
                else:
                    result = await self.translator.translate_with_api(prompt, model_name)
            except Exception as exc:
                # Identify the exact file in progress so the API/UI can explain
                # why a multi-file migration stopped partway through.
                logger.exception(
                    "Translation failed for %s with model %s", source_path, model_name
                )
                if not continue_on_error:
                    raise RuntimeError(
                        f"Translation failed for '{source_path}' with model '{model_name}': {exc}"
                    ) from exc
                completed.append({
                    "source_path": source_path,
                    "target_path": target_path,
                    "model_name": model_name,
                    "latency_seconds": 0.0,
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                if progress_callback:
                    await progress_callback({
                        "migration_id": migration_id,
                        "current_file": source_path,
                        "target_file": target_path,
                        "completed_files": index,
                        "total_files": len(ordered_paths),
                        "status": "FILE_FAILED",
                    })
                continue
            generated = self._strip_fence(result.translated_code)
            target_file = (output_root / target_path).resolve()
            if not target_file.is_relative_to(output_root.resolve()):
                raise ValueError(f"Mapped target path escaped output directory: {target_path}")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(generated.rstrip() + "\n", encoding="utf-8")
            translated_context[source_path] = generated
            record = {
                "source_path": source_path,
                "target_path": target_path,
                "model_name": result.model_name,
                "latency_seconds": result.execution_time_seconds,
                "status": "TRANSLATED",
            }
            completed.append(record)
            if progress_callback:
                await progress_callback({
                    "migration_id": migration_id,
                    "current_file": source_path,
                    "target_file": target_path,
                    "completed_files": index,
                    "total_files": len(ordered_paths),
                    "status": "TRANSLATED",
                })

        return {
            "migration_id": migration_id,
            "model_name": model_name,
            "source_type": structure["source_type"],
            "target_framework": target_framework,
            "source_tree": sorted(file_by_path),
            "target_tree": sorted(p.relative_to(output_root).as_posix() for p in output_root.rglob("*") if p.is_file()),
            "translation_order": ordered_paths,
            "files": completed,
            "dependencies": dependency_result,
            "target_root": str(output_root),
        }

    @staticmethod
    def _layer(path: str) -> str:
        lower = path.lower()
        if any(value in lower for value in ("model", "entity", "schema")):
            return "entity"
        if any(value in lower for value in ("repository", "dao", "database", "db/")):
            return "repository"
        if "service" in lower:
            return "service"
        if any(value in lower for value in ("route", "controller", "handler")):
            return "controller"
        return "other"

    @staticmethod
    def _import_tokens(content: str) -> set[str]:
        patterns = (
            r"(?:import|from)\s+[\"']([^\"']+)[\"']",
            r"require\(\s*[\"']([^\"']+)[\"']\s*\)",
            r"(?:import|include)\s+[\"']([^\"']+)[\"']",
        )
        return {match for pattern in patterns for match in re.findall(pattern, content)}

    @staticmethod
    def _redact_sensitive_content(path: str, content: str) -> str:
        if Path(path).name.lower() not in {".env", ".env.example"}:
            # Keep credentials and tokens out of model prompts even when a legacy
            # project has hard-coded values in a JavaScript/Python config file.
            content = re.sub(
                r"(?i)(password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)"
                r"(\s*[:=]\s*)(['\"`])[^'\"`]*\3",
                lambda match: f"{match.group(1)}{match.group(2)}${{{match.group(1).upper().replace('-', '_')}}}",
                content,
            )
            return re.sub(
                r"(?i)(mongodb(?:\+srv)?://)[^/@\s:'\"]+:[^/@\s'\"]+@",
                r"\1${MONGODB_CREDENTIALS}@",
                content,
            )
        lines = []
        for line in content.splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                lines.append(line)
                continue
            key, _ = line.split("=", 1)
            lines.append(f"{key}=${{{key}}}")
        return "\n".join(lines)

    @staticmethod
    def _build_file_prompt(
        *, source_path: str, target_path: str, source_code: str,
        target_framework: str, dependency_info: dict[str, Any], previous_context: str,
    ) -> str:
        guardrails = ""
        if target_framework == "spring-boot":
            guardrails = (
                "FRAMEWORK CONSTRAINTS:\n"
                "- Target is Spring Boot (Java), NOT Android. NEVER use android.*, androidx.*, or Activity.\n"
                "- Use Spring Boot annotations (@Component, @Service, @RestController, @Repository) or standard Java POJOs.\n"
                "- Translate the source file's specific data structures, functions, and state faithfully into the target file."
            )
        elif target_framework == "go-fiber":
            guardrails = (
                "FRAMEWORK CONSTRAINTS:\n"
                "- Target is Go Fiber. Use idiomatic Go packages, structs, and Fiber route handlers."
            )

        return f"""You are Lexora, a senior software engineer migrating a complete repository.
Translate this one source file into idiomatic production-quality code for {target_framework}.
Preserve behavior, public API contracts, validation, error handling, and asynchronous semantics.
The output must be only the complete target file contents, without markdown or explanation.

Source file: {source_path}
Required target file: {target_path}
Target dependencies: {json_for_prompt(dependency_info)}

{guardrails}

Previously translated dependency files. Match their exact type, class, method, and field names:
{previous_context}

Source code:
```source
{source_code}
```
"""

    @staticmethod
    def _strip_fence(code: str) -> str:
        stripped = code.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[^\n]*\n", "", stripped)
            stripped = re.sub(r"\n```\s*$", "", stripped)
        return stripped.strip()

    @staticmethod
    def _write_scaffold(root: Path, framework: str, dependencies: dict[str, Any]) -> None:
        if framework == "spring-boot":
            application = root / "src/main/java/com/lexora/LexoraApplication.java"
            application.parent.mkdir(parents=True, exist_ok=True)
            application.write_text(
                "package com.lexora;\n\n"
                "import org.springframework.boot.SpringApplication;\n"
                "import org.springframework.boot.autoconfigure.SpringBootApplication;\n\n"
                "@SpringBootApplication\npublic class LexoraApplication {\n"
                "    public static void main(String[] args) {\n"
                "        SpringApplication.run(LexoraApplication.class, args);\n"
                "    }\n}\n",
                encoding="utf-8",
            )
            props = root / "src/main/resources/application.properties"
            props.parent.mkdir(parents=True, exist_ok=True)
            if not props.exists():
                props.write_text(
                    "spring.application.name=migrated-application\n"
                    "spring.data.mongodb.uri=${MONGODB_URI:mongodb://localhost:27017/lexora_db}\n",
                    encoding="utf-8",
                )
        else:
            main = root / "cmd/server/main.go"
            main.parent.mkdir(parents=True, exist_ok=True)
            main.write_text(
                "package main\n\nimport (\n\t\"log\"\n\t\"github.com/gofiber/fiber/v2\"\n)\n\n"
                "func main() {\n\tapp := fiber.New()\n\tlog.Fatal(app.Listen(\":3000\"))\n}\n",
                encoding="utf-8",
            )

    @staticmethod
    def _write_env_template(root: Path, framework: str, content: str) -> None:
        entries = []
        for line in content.splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key = line.split("=", 1)[0].strip()
            if not key:
                continue
            if framework == "spring-boot":
                property_key = {
                    "PORT": "server.port",
                    "MONGODB_URI": "spring.data.mongodb.uri",
                    "MONGODB_DB_NAME": "spring.data.mongodb.database",
                }.get(key, key.lower().replace("_", "."))
                entries.append(f"{property_key}=${{{key}:}}")
            else:
                entries.append(f"{key}=")
        if framework == "spring-boot":
            target = root / "src/main/resources/application.properties"
            target.parent.mkdir(parents=True, exist_ok=True)
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            merged = existing.rstrip() + ("\n" if existing.strip() else "") + "\n".join(entries) + "\n"
        else:
            target = root / "config/application.env.example"
            target.parent.mkdir(parents=True, exist_ok=True)
            merged = "\n".join(entries) + "\n"
        target.write_text(merged, encoding="utf-8")


def json_for_prompt(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)
