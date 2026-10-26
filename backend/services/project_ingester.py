"""Safe zip ingestion for repository migrations."""

from __future__ import annotations

import io
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "outputs"
IGNORED_DIRS = {"node_modules", "venv", ".venv", ".git", "dist", "target", "__pycache__"}
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_FILES = 5000
TEXT_EXTENSIONS = {
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".py", ".java", ".go",
    ".json", ".yaml", ".yml", ".xml", ".properties", ".toml", ".ini", ".sql",
    ".html", ".css", ".scss", ".md", ".txt", ".sh", ".env", ".gradle", ".mod",
    ".lock", ".gitignore", ".dockerignore", ".csv", ".tsv", ".svg",
}


class ProjectIngester:
    FRAMEWORK_SIGNATURES = {
        "node": {"name": "Node.js", "type": "node", "icon": "nodejs"},
        "express": {"name": "Node.js / Express", "type": "node", "icon": "nodejs"},
        "nestjs": {"name": "Node.js / NestJS", "type": "node", "icon": "nestjs"},
        "fastify": {"name": "Node.js / Fastify", "type": "node", "icon": "nodejs"},
        "react-native": {"name": "Expo / React Native", "type": "node", "icon": "react"},
        "spring": {"name": "Java / Spring Boot", "type": "spring", "icon": "java"},
        "java": {"name": "Java / JVM", "type": "spring", "icon": "java"},
        "python": {"name": "Python / FastAPI", "type": "python", "icon": "python"},
        "django": {"name": "Python / Django", "type": "python", "icon": "python"},
        "flask": {"name": "Python / Flask", "type": "python", "icon": "python"},
        "go": {"name": "Go / Fiber", "type": "go", "icon": "golang"},
        "unknown": {"name": "Generic Backend", "type": "unknown", "icon": "code"},
    }

    def __init__(self, output_root: Path | None = None) -> None:
        self.output_root = (output_root or OUTPUT_ROOT).resolve()

    def ingest_zip(self, archive_bytes: bytes, migration_id: str) -> dict[str, Any]:
        if len(archive_bytes) > MAX_ARCHIVE_BYTES:
            raise ValueError("Uploaded archive exceeds the 50 MiB limit")
        if not migration_id or any(c not in "0123456789abcdef-" for c in migration_id.lower()):
            raise ValueError("Invalid migration ID")

        migration_root = (self.output_root / migration_id).resolve()
        source_root = (migration_root / "source").resolve()
        if not source_root.is_relative_to(self.output_root) or not migration_root.is_relative_to(self.output_root):
            raise ValueError("Invalid staging directory")
        if source_root.exists():
            shutil.rmtree(source_root)
        source_root.mkdir(parents=True, exist_ok=True)

        total_size = 0
        accepted_files = 0
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                members = archive.infolist()
                if len(members) > MAX_FILES * 2:
                    raise ValueError("Archive contains too many entries")
                for info in members:
                    member = PurePosixPath(info.filename.replace("\\", "/"))
                    if member.is_absolute() or ".." in member.parts or not member.parts:
                        raise ValueError(f"Unsafe archive path: {info.filename}")
                    mode = info.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise ValueError(f"Symbolic links are not allowed: {info.filename}")
                    if any(part.lower() in IGNORED_DIRS for part in member.parts):
                        continue
                    total_size += info.file_size
                    if total_size > MAX_UNCOMPRESSED_BYTES:
                        raise ValueError("Archive expands beyond the 200 MiB limit")
                    if info.is_dir():
                        continue
                    if accepted_files >= MAX_FILES:
                        raise ValueError("Archive contains too many source files")
                    destination = (source_root / Path(*member.parts)).resolve()
                    if not destination.is_relative_to(source_root):
                        raise ValueError(f"Unsafe archive path: {info.filename}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as src, destination.open("wb") as dst:
                        shutil.copyfileobj(src, dst, length=1024 * 1024)
                    accepted_files += 1
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            shutil.rmtree(source_root, ignore_errors=True)
            raise ValueError(f"Unable to extract project archive: {exc}") from exc
        except Exception:
            shutil.rmtree(source_root, ignore_errors=True)
            raise

        files = self.collect_source_files(source_root)
        if not files:
            shutil.rmtree(source_root, ignore_errors=True)
            raise ValueError("Archive did not contain any supported text source files")
        project_profile = self.detect_project_profile(source_root)
        detected_framework = self.primary_framework(project_profile)
        return {
            "source_root": source_root,
            "files": files,
            "source_tree": self.build_tree(files),
            "detected_framework": detected_framework,
            "project_profile": project_profile,
        }

    @classmethod
    def detect_framework(cls, source_root: Path) -> dict[str, str]:
        """Detect the primary backend framework, then fall back to a frontend/runtime manifest."""
        profile = cls.detect_project_profile(source_root)
        return cls.primary_framework(profile)

    @classmethod
    def primary_framework(cls, profile: dict[str, Any]) -> dict[str, str]:
        components = profile["components"]
        # Prefer the server-side framework when this archive is a full-stack
        # repository; the mapper targets backend frameworks, not browser UIs.
        backend_component = next(
            (item for item in components if item["role"] == "backend"), None
        )
        if backend_component:
            return dict(backend_component["detected_framework"])
        frontend_component = next(
            (item for item in components if item["role"] == "frontend"), None
        )
        if frontend_component:
            return dict(frontend_component["detected_framework"])
        other_component = next(iter(components), None)
        if other_component:
            return dict(other_component["detected_framework"])
        return dict(cls.FRAMEWORK_SIGNATURES["unknown"])

    @classmethod
    def detect_project_profile(cls, source_root: Path) -> dict[str, Any]:
        """Detect multiple app tiers and data platforms present in a repository."""
        manifests: dict[str, list[Path]] = {}
        for path in source_root.rglob("*"):
            relative = path.relative_to(source_root)
            ignored = any(part.lower() in IGNORED_DIRS for part in relative.parts)
            # Downloaded target archives often have a single enclosing `target/`
            # directory. Inspect that wrapper while still ignoring Maven build output.
            wrapper_target = len(relative.parts) > 1 and relative.parts[0].lower() == "target"
            if ignored and not wrapper_target:
                continue
            if path.is_file():
                manifests.setdefault(path.name.lower(), []).append(path)

        def read_manifest(names: tuple[str, ...]) -> str:
            for name in names:
                for candidate in manifests.get(name, []):
                    try:
                        return candidate.read_text(encoding="utf-8", errors="replace").lower()
                    except OSError:
                        continue
            return ""

        package = read_manifest(("package.json",))
        python_sources: list[str] = []
        for path in source_root.rglob("*.py"):
            relative = path.relative_to(source_root)
            if any(part.lower() in IGNORED_DIRS for part in relative.parts):
                continue
            try:
                python_sources.append(path.read_text(encoding="utf-8", errors="replace").lower())
            except OSError:
                continue
        python_code = "\n".join(python_sources)
        requirements = read_manifest(("requirements.txt", "pyproject.toml", "pipfile"))
        java_config = read_manifest(("pom.xml", "build.gradle", "build.gradle.kts"))
        node_kind = None
        if manifests.get("package.json"):
            if any(marker in package for marker in ('"react-native"', '"expo"')):
                node_kind = "react-native"
            elif '"@nestjs/core"' in package:
                node_kind = "nestjs"
            elif '"fastify"' in package:
                node_kind = "fastify"
            elif '"express"' in package:
                node_kind = "express"
            elif '"react"' in package or any(
                path.name.lower() in {"vite.config.js", "vite.config.ts", "vite.config.jsx", "vite.config.tsx"}
                for path in source_root.rglob("vite.config.*")
            ):
                node_kind = "react-vite"
            else:
                node_kind = "node"

        python_kind = None
        if "django" in requirements or re.search(r"(?m)^\s*(?:from|import)\s+django\b", python_code):
            python_kind = "django"
        elif "fastapi" in requirements or (
            re.search(r"(?m)^\s*(?:from|import)\s+fastapi\b", python_code)
            and re.search(r"\bfastapi\s*\(", python_code)
        ):
            python_kind = "python"
        elif "flask" in requirements or (
            re.search(r"(?m)^\s*(?:from|import)\s+flask\b", python_code)
            and re.search(r"\bflask\s*\(", python_code)
        ):
            python_kind = "flask"
        elif any(manifests.get(name) for name in ("requirements.txt", "pyproject.toml", "pipfile")):
            python_kind = "python"

        java_kind = None
        if manifests.get("pom.xml") or manifests.get("build.gradle") or manifests.get("build.gradle.kts"):
            java_kind = "spring" if "spring-boot" in java_config or "springframework" in java_config else "java"

        components: list[dict[str, Any]] = []
        if node_kind:
            framework = dict(cls.FRAMEWORK_SIGNATURES.get(node_kind, cls.FRAMEWORK_SIGNATURES["node"]))
            framework["name"] = {
                "react-vite": "React / Vite",
            }.get(node_kind, framework["name"])
            components.append({"role": "frontend" if node_kind in {"react-vite", "react-native"} else "node-service", "detected_framework": framework})
        if python_kind:
            components.append({"role": "backend", "detected_framework": dict(cls.FRAMEWORK_SIGNATURES[python_kind])})
        if java_kind:
            components.append({"role": "backend", "detected_framework": dict(cls.FRAMEWORK_SIGNATURES[java_kind])})
        if manifests.get("go.mod"):
            components.append({"role": "backend", "detected_framework": dict(cls.FRAMEWORK_SIGNATURES["go"])})

        data_platforms = []
        directories = {part.lower() for path in source_root.rglob("*") for part in path.relative_to(source_root).parts}
        if "hdfs" in directories or "mapreduce" in directories:
            data_platforms.append("Hadoop / HDFS / MapReduce")
        if "hive" in directories or any(source_root.rglob("*.hql")):
            data_platforms.append("Apache Hive")
        if "pig" in directories or any(source_root.rglob("*.pig")):
            data_platforms.append("Apache Pig")
        if "spark" in directories or "pyspark" in python_code:
            data_platforms.append("Apache Spark / PySpark")
        if "mongodb" in directories or "pymongo" in python_code or "mongoengine" in python_code:
            data_platforms.append("MongoDB")

        profile_kind = "multi_component" if len(components) > 1 or data_platforms else (
            "single_component" if components else "unknown"
        )
        full_supported = profile_kind == "single_component" and not data_platforms
        if profile_kind == "multi_component":
            warning = (
                "This repository contains multiple application/data components. Lexora can generate a backend-target draft, "
                "but current migration does not preserve the whole frontend + backend + analytics stack as a working system."
            )
        elif components:
            warning = "Migration output is a generated draft; build and behavior still need verification."
        else:
            warning = "No supported framework signature was detected; migration may be inaccurate."

        return {
            "kind": profile_kind,
            "components": components,
            "data_platforms": data_platforms,
            "full_repository_migration_supported": full_supported,
            "warning": warning,
        }

    @staticmethod
    def collect_source_files(source_root: Path) -> list[dict[str, str]]:
        files: list[dict[str, str]] = []
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or any(p.lower() in IGNORED_DIRS for p in path.relative_to(source_root).parts):
                continue
            if path.suffix.lower() not in TEXT_EXTENSIONS and path.name not in {
                "Dockerfile", "Makefile", "Procfile", ".env", ".env.example",
                ".gitignore", ".dockerignore", "package.json", "requirements.txt",
            }:
                continue
            try:
                content = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                continue
            files.append({"path": path.relative_to(source_root).as_posix(), "content": content})
        return files

    @staticmethod
    def build_tree(files: list[dict[str, str]]) -> list[str]:
        return [item["path"] for item in files]
