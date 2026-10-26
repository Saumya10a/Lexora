"""Translate common source package manifests into target build manifests."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class DependencyTranslator:
    SPRING_ARTIFACTS = {
        "express": ("org.springframework.boot", "spring-boot-starter-web"),
        "mongoose": ("org.springframework.boot", "spring-boot-starter-data-mongodb"),
        "mongodb": ("org.springframework.boot", "spring-boot-starter-data-mongodb"),
        "jsonwebtoken": ("io.jsonwebtoken", "jjwt-api"),
        "bcrypt": ("org.springframework.security", "spring-security-crypto"),
        "cors": ("org.springframework.boot", "spring-boot-starter-web"),
        "dotenv": ("org.springframework.boot", "spring-boot-starter"),
    }
    GO_MODULES = {
        "express": "github.com/gofiber/fiber/v2",
        "mongoose": "go.mongodb.org/mongo-driver",
        "mongodb": "go.mongodb.org/mongo-driver",
        "jsonwebtoken": "github.com/golang-jwt/jwt/v5",
        "bcrypt": "golang.org/x/crypto",
        "cors": "github.com/gofiber/fiber/v2/middleware/cors",
    }

    def translate(self, source_root: Path, target_root: Path, target_framework: str) -> dict[str, Any]:
        source_root, target_root = Path(source_root), Path(target_root)
        package_candidates = sorted(source_root.rglob("package.json"))
        package_path = package_candidates[0] if package_candidates else source_root / "package.json"
        requirements_candidates = sorted(source_root.rglob("requirements.txt"))
        requirements = requirements_candidates[0] if requirements_candidates else source_root / "requirements.txt"
        packages: dict[str, str] = {}
        if package_path.is_file():
            try:
                package_data = json.loads(package_path.read_text(encoding="utf-8"))
                packages.update(package_data.get("dependencies", {}))
                packages.update(package_data.get("devDependencies", {}))
            except (json.JSONDecodeError, OSError) as exc:
                raise ValueError(f"Unable to parse package.json: {exc}") from exc
        if requirements.is_file():
            for line in requirements.read_text(encoding="utf-8").splitlines():
                match = re.match(r"\s*([A-Za-z0-9_.-]+)\s*(?:[=<>!~].*)?$", line)
                if match and not line.lstrip().startswith("#"):
                    packages[match.group(1).lower()] = ""

        normalized_framework = target_framework.lower()
        target_root.mkdir(parents=True, exist_ok=True)
        translated: list[str] = []
        if normalized_framework == "spring-boot":
            translated = self._write_pom(target_root, packages)
            manifest = "pom.xml"
        elif normalized_framework == "go-fiber":
            translated = self._write_go_mod(target_root, packages)
            manifest = "go.mod"
        else:
            raise ValueError(f"Unsupported target framework: {target_framework}")
        return {"source_dependencies": sorted(packages), "target_dependencies": translated, "manifest": manifest}

    def _write_pom(self, root: Path, packages: dict[str, str]) -> list[str]:
        artifacts = {"org.springframework.boot:spring-boot-starter-web", "org.springframework.boot:spring-boot-starter-test"}
        for package in packages:
            mapped = self.SPRING_ARTIFACTS.get(package.lower())
            if mapped:
                artifacts.add(":".join(mapped))
        dependency_xml = "\n".join(
            f"        <dependency><groupId>{group}</groupId><artifactId>{artifact}</artifactId></dependency>"
            for group, artifact in sorted(tuple(item.split(":", 1) for item in artifacts))
        )
        pom = f'''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.lexora</groupId><artifactId>migrated-application</artifactId><version>0.0.1-SNAPSHOT</version>
  <parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId><version>3.2.5</version><relativePath/></parent>
  <properties><java.version>17</java.version></properties>
  <dependencies>
{dependency_xml}
  </dependencies>
  <build><plugins><plugin><groupId>org.springframework.boot</groupId><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build>
</project>
'''
        (root / "pom.xml").write_text(pom, encoding="utf-8")
        return sorted(artifacts)

    def _write_go_mod(self, root: Path, packages: dict[str, str]) -> list[str]:
        modules = {self.GO_MODULES[name.lower()] for name in packages if name.lower() in self.GO_MODULES}
        modules.add("github.com/gofiber/fiber/v2")
        go_mod = "module lexora-migrated\n\ngo 1.22\n\nrequire (\n" + "".join(f"\t{module} latest\n" for module in sorted(modules)) + ")\n"
        (root / "go.mod").write_text(go_mod, encoding="utf-8")
        return sorted(modules)
