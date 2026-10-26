"""Offline smoke test for archive ingestion, path mapping, DAG order, and packaging."""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

from backend.services.graph_orchestrator import MigrationGraph
from backend.services.dependency_translator import DependencyTranslator
from backend.services.project_ingester import ProjectIngester
from backend.services.structural_mapper import FrameworkStructuralMapper


class DeterministicTranslator:
    """Small offline stand-in: exercises orchestration without API calls or GPU loading."""

    async def translate_with_api(self, prompt: str, model_name: str) -> SimpleNamespace:
        return self._result(prompt, model_name)

    async def translate_with_local_hf(self, prompt: str) -> SimpleNamespace:
        return self._result(prompt, "fine_tuned_hf")

    @staticmethod
    def _result(prompt: str, model_name: str) -> SimpleNamespace:
        match = re.search(r"Required target file: (.+)", prompt)
        target = match.group(1) if match else "src/main/java/com/lexora/components/Migrated.java"
        class_name = Path(target).stem
        package_path = target.split("src/main/java/", 1)[-1].rsplit("/", 1)[0]
        package = package_path.replace("/", ".")
        if "/entities/" in target:
            code = f"package {package};\npublic class {class_name} {{ private String id; }}"
        elif "/repositories/" in target:
            code = f"package {package};\npublic interface {class_name} {{ }}"
        elif "/services/" in target:
            code = f"package {package};\npublic class {class_name} {{ public String status() {{ return \"ok\"; }} }}"
        elif "/controllers/" in target:
            code = f"package {package};\npublic class {class_name} {{ public String health() {{ return \"ok\"; }} }}"
        else:
            code = f"package {package};\npublic class {class_name} {{ }}"
        return SimpleNamespace(model_name=model_name, translated_code=code, execution_time_seconds=0.001)


def make_mock_node_zip() -> bytes:
    files = {
        "demo/package.json": json.dumps({"dependencies": {"express": "^4.18.0", "mongoose": "^8.0.0"}}),
        "demo/.env": "PORT=3000\nMONGODB_URI=mongodb://user:secret@localhost/app\nJWT_SECRET=do-not-copy-this\n",
        "demo/src/models/User.js": "class User { constructor(id) { this.id = id; } }\nmodule.exports = User;",
        "demo/src/repositories/UserRepository.js": "const User = require('../models/User');\nclass UserRepository {}\nmodule.exports = UserRepository;",
        "demo/src/services/UserService.js": "const UserRepository = require('../repositories/UserRepository');\nclass UserService {}\nmodule.exports = UserService;",
        "demo/src/routes/userRoutes.js": "const UserService = require('../services/UserService');\nconst router = require('express').Router();\nmodule.exports = router;",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


async def run_smoke_test() -> tuple[str, Path, list[str]]:
    migration_id = str(uuid.uuid4())
    output_root = Path(__file__).resolve().parent / "outputs"
    ingested = ProjectIngester(output_root).ingest_zip(make_mock_node_zip(), migration_id)
    mapping = FrameworkStructuralMapper().map_paths(ingested["files"], "spring-boot")
    assert mapping["mapping"]["demo/src/routes/userRoutes.js"].endswith("controllers/UserController.java")
    result = await MigrationGraph(DeterministicTranslator()).migrate_project(
        migration_id=migration_id,
        source_root=ingested["source_root"],
        files=ingested["files"],
        target_framework="spring-boot",
        model_name="openai/gpt-oss-20b",
    )
    target = Path(result["target_root"])
    assert (target / "pom.xml").is_file()
    assert (target / "src/main/java/com/lexora/LexoraApplication.java").is_file()
    assert (target / "src/main/java/com/lexora/controllers/UserController.java").is_file()
    assert (target / "src/main/java/com/lexora/entities/User.java").is_file()
    ET.parse(target / "pom.xml")
    assert result["translation_order"].index("demo/src/models/User.js") < result["translation_order"].index("demo/src/repositories/UserRepository.js")
    assert result["translation_order"].index("demo/src/repositories/UserRepository.js") < result["translation_order"].index("demo/src/services/UserService.js")
    assert result["translation_order"].index("demo/src/services/UserService.js") < result["translation_order"].index("demo/src/routes/userRoutes.js")
    properties = (target / "src/main/resources/application.properties").read_text(encoding="utf-8")
    assert "secret@" not in properties and "do-not-copy-this" not in properties
    archive_path = ingested["source_root"].parent / "test-target.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in target.rglob("*"):
            if path.is_file():
                archive.write(path, Path("target") / path.relative_to(target))
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert "target/pom.xml" in names
        assert "target/src/main/java/com/lexora/controllers/UserController.java" in names
    go_target = ingested["source_root"].parent / "go-target"
    go_deps = DependencyTranslator().translate(ingested["source_root"], go_target, "go-fiber")
    go_map = FrameworkStructuralMapper().map_paths(ingested["files"], "go-fiber")
    assert (go_target / "go.mod").is_file()
    assert "github.com/gofiber/fiber/v2" in go_deps["target_dependencies"]
    assert go_map["mapping"]["demo/src/routes/userRoutes.js"] == "internal/handler/userroutes.go"
    hardcoded = MigrationGraph._redact_sensitive_content(
        "demo/src/config/database.js",
        "const password = 'do-not-send';\nconst uri = 'mongodb://admin:secret@db/app';",
    )
    assert "do-not-send" not in hardcoded and "admin:secret" not in hardcoded
    tree = list(result["target_tree"])
    return migration_id, target, tree


def main() -> int:
    print("=" * 70)
    print("LEXORA PROJECT MIGRATION PIPELINE SMOKE TEST")
    print("=" * 70)
    try:
        smoke_test = run_smoke_test()
        try:
            smoke_test.send(None)
        except StopIteration as completed:
            migration_id, _, tree = completed.value
        else:
            smoke_test.close()
            raise RuntimeError("Offline smoke test unexpectedly attempted asynchronous I/O")
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1
    print(f"Mock migration ID          : {migration_id}")
    print("Archive ingestion          : PASS")
    print("Structural mapping         : PASS (Express routes/models -> Spring layers)")
    print("Translation DAG order      : PASS (entities -> repositories -> services -> controllers)")
    print("Dependency manifest        : PASS (pom.xml)")
    print("Secret-safe env conversion : PASS")
    print(f"Target files generated     : {len(tree)}")
    print("Target archive packaging   : PASS")
    print("Note: Uses an offline deterministic translator; live LLM translation requires the API/model configuration.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
