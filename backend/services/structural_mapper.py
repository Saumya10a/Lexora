"""Map source repository paths to idiomatic target framework paths."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


class FrameworkStructuralMapper:
    FRAMEWORKS = {"spring-boot", "go-fiber"}
    TARGET_CATALOG = (
        {"id": "spring-boot", "label": "Spring Boot · Java", "language": "Java", "icon": "java"},
        {"id": "go-fiber", "label": "Go Fiber · Go", "language": "Go", "icon": "golang"},
    )
    # Explicit framework bridges take precedence over the general layer heuristics.
    ROUTE_RULES = {
        ("node", "spring-boot"): "node_routes_to_spring_controllers",
        ("python", "go-fiber"): "python_routers_to_fiber_handlers",
    }

    def map_paths(
        self,
        source_files: list[dict[str, str]] | list[str],
        target_framework: str | None = None,
        *,
        source_type: str = "unknown",
        target_type: str | None = None,
    ) -> dict[str, Any]:
        framework = self.normalize_framework(target_type or target_framework or "")
        source_kind = self.normalize_source_type(source_type)
        paths = [item["path"] if isinstance(item, dict) else item for item in source_files]
        mapping: dict[str, str] = {}
        used: set[str] = set()
        for raw in paths:
            clean_raw = str(raw).replace("\\", "/")
            source_path = PurePosixPath(clean_raw)
            lower = clean_raw.lower()
            name = source_path.stem
            class_name = self._class_name(name)
            if source_path.name.lower() in {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "requirements.txt", "pyproject.toml", "pipfile", "pom.xml", "build.gradle", "go.mod"}:
                continue
            if source_path.name.lower() in {".env", ".env.example"}:
                target = "src/main/resources/application.properties" if framework == "spring-boot" else "config/application.env.example"
            elif self._uses_route_rule(source_kind, framework, source_path):
                rule = self.ROUTE_RULES[(source_kind, framework)]
                target = getattr(self, rule)(source_path)
            elif framework == "spring-boot":
                if source_path.suffix.lower() in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".py", ".java"}:
                    target = self._spring_path(lower, source_path, class_name)
                elif source_path.suffix.lower() in {".yml", ".yaml", ".properties", ".sql", ".json"}:
                    target = f"src/main/resources/{source_path.as_posix()}"
                elif any(part in {"frontend", "client", "ui", "web"} for part in source_path.parts):
                    target = f"frontend/{source_path.as_posix()}"
                elif any(part in {"data", "dataset", "datasets"} for part in source_path.parts):
                    target = f"data/{source_path.as_posix()}"
                else:
                    target = f"docs/{source_path.as_posix()}"
            else:
                if source_path.suffix.lower() in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".py", ".go"}:
                    target = self._fiber_path(lower, source_path, source_path)
                elif source_path.suffix.lower() in {".json", ".yml", ".yaml", ".toml", ".properties", ".sql"}:
                    target = f"config/{source_path.as_posix()}"
                elif any(part in {"frontend", "client", "ui", "web"} for part in source_path.parts):
                    target = f"frontend/{source_path.as_posix()}"
                elif any(part in {"data", "dataset", "datasets"} for part in source_path.parts):
                    target = f"data/{source_path.as_posix()}"
                else:
                    target = f"docs/{source_path.as_posix()}"
            if target in used:
                stem, suffix = target.rsplit(".", 1) if "." in target else (target, "")
                target = f"{stem}_{self._class_name(name)}.{suffix}" if suffix else f"{stem}_{self._class_name(name)}"
            used.add(target)
            mapping[clean_raw] = target
            mapping[str(raw)] = target
        return {
            "source_type": source_kind,
            "target_framework": framework,
            "mapping": mapping,
            "target_tree": sorted(set(mapping.values())),
        }

    @classmethod
    def normalize_framework(cls, value: str) -> str:
        aliases = {"spring": "spring-boot", "springboot": "spring-boot", "spring-boot": "spring-boot", "fiber": "go-fiber", "go": "go-fiber", "go-fiber": "go-fiber"}
        normalized = aliases.get(value.strip().lower())
        if normalized not in cls.FRAMEWORKS:
            raise ValueError(f"Unsupported target framework '{value}'. Choose spring-boot or go-fiber.")
        return normalized

    @classmethod
    def available_targets(cls, source_type: str) -> list[dict[str, Any]]:
        """Return only targets for which the current structural mapper has a backend."""
        source = cls.normalize_source_type(source_type)
        return [
            {**target, "recommended": (source, target["id"]) in cls.ROUTE_RULES}
            for target in cls.TARGET_CATALOG
        ]

    @staticmethod
    def normalize_source_type(value: str | None) -> str:
        aliases = {
            "node": "node", "nodejs": "node", "javascript": "node", "express": "node",
            "spring": "spring", "java": "spring", "spring-boot": "spring",
            "python": "python", "fastapi": "python", "django": "python",
            "go": "go", "golang": "go", "fiber": "go",
            "unknown": "unknown", "generic": "unknown", None: "unknown",
        }
        normalized = aliases.get(value.strip().lower() if value else None)
        if normalized is None:
            raise ValueError(f"Unsupported source framework type '{value}'")
        return normalized

    @classmethod
    def _uses_route_rule(cls, source_type: str, target: str, path: PurePosixPath) -> bool:
        source = cls.normalize_source_type(source_type)
        if (source, target) not in cls.ROUTE_RULES:
            return False
        parts = tuple(part.lower() for part in path.parts)
        if source == "node":
            return "routes" in parts and path.suffix.lower() in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
        return "routers" in parts and path.suffix.lower() == ".py"

    @classmethod
    def node_routes_to_spring_controllers(cls, source: PurePosixPath) -> str:
        base = re.sub(r"(?i)(routes?)$", "", source.stem)
        return f"src/main/java/com/lexora/controllers/{cls._class_name(base)}Controller.java"

    @staticmethod
    def python_routers_to_fiber_handlers(source: PurePosixPath) -> str:
        stem = re.sub(r"(?i)(router|routes?)$", "", source.stem).strip("_- ") or source.stem
        return f"cmd/api/handlers/{stem.lower().replace('-', '_')}.go"

    @staticmethod
    def _class_name(name: str) -> str:
        parts = re.findall(r"[A-Za-z0-9]+", name)
        return "".join(part[:1].upper() + part[1:] for part in parts) or "MigratedFile"

    def _spring_path(self, lower: str, source: PurePosixPath, class_name: str) -> str:
        parts_lower = [part.lower() for part in source.parts]
        if any(part in {"frontend", "client", "ui", "web"} for part in parts_lower) or source.suffix.lower() in {".jsx", ".tsx", ".vue", ".svelte", ".html", ".css", ".scss", ".less"}:
            return f"frontend/{source.as_posix()}"
        if any(part in {"spark", "mapreduce", "hdfs", "hive", "pig"} for part in parts_lower) or source.suffix.lower() in {".hql", ".pig"}:
            return f"pipeline/{source.as_posix()}"
        if any(part in {"scripts", "script"} for part in parts_lower):
            return f"scripts/{source.as_posix()}"
        if any(part in {"tests", "test"} for part in parts_lower):
            return f"tests/{source.as_posix()}"
        if any(part in {"data", "dataset", "datasets"} for part in parts_lower):
            return f"data/{source.as_posix()}"

        config_name = source.stem.lower()
        if source.suffix.lower() in {".js", ".mjs", ".ts", ".py", ".java"} and (
            config_name in {"config", "settings", "database", "db", "mongo"}
            or "/config/" in f"/{lower}/"
        ):
            return "src/main/resources/application.properties"
        if "model" in lower or "entity" in lower or "schema" in lower:
            layer, suffix = "entities", class_name
        elif "repository" in lower or "dao" in lower:
            layer, suffix = "repositories", class_name
        elif "service" in lower:
            layer, suffix = "services", class_name
        elif "route" in lower or "controller" in lower or "handler" in lower:
            base = re.sub(r"(?i)(routes?|controller|handler)$", "", source.stem)
            suffix = self._class_name(base) + "Controller"
            layer = "controllers"
        elif source.suffix.lower() in {".yml", ".yaml", ".properties"}:
            return "src/main/resources/" + source.name
        else:
            layer, suffix = "components", class_name
        return f"src/main/java/com/lexora/{layer}/{suffix}.java"

    def _fiber_path(self, lower: str, source: PurePosixPath, original: PurePosixPath) -> str:
        parts_lower = [part.lower() for part in source.parts]
        if any(part in {"frontend", "client", "ui", "web"} for part in parts_lower) or source.suffix.lower() in {".jsx", ".tsx", ".vue", ".svelte", ".html", ".css", ".scss", ".less"}:
            return f"frontend/{source.as_posix()}"
        if any(part in {"spark", "mapreduce", "hdfs", "hive", "pig"} for part in parts_lower) or source.suffix.lower() in {".hql", ".pig"}:
            return f"pipeline/{source.as_posix()}"
        if any(part in {"scripts", "script"} for part in parts_lower):
            return f"scripts/{source.as_posix()}"
        if any(part in {"tests", "test"} for part in parts_lower):
            return f"tests/{source.as_posix()}"
        if any(part in {"data", "dataset", "datasets"} for part in parts_lower):
            return f"data/{source.as_posix()}"

        if "model" in lower or "entity" in lower or "schema" in lower:
            directory = "internal/entity"
        elif "repository" in lower or "dao" in lower or "data" in lower:
            directory = "internal/repository"
        elif "service" in lower:
            directory = "internal/service"
        elif "route" in lower or "controller" in lower or "handler" in lower:
            directory = "internal/handler"
        elif source.suffix.lower() in {".yml", ".yaml", ".properties"}:
            return "config/" + source.name
        else:
            directory = "internal/migrated"
        return f"{directory}/{original.stem.lower().replace('-', '_')}.go"
