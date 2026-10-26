"""Build and run isolated local containers for completed target projects."""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

from backend.services.project_ingester import OUTPUT_ROOT

try:
    import docker
except ModuleNotFoundError:  # API can start even when Docker is not installed.
    docker = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
MAX_TARGET_FILES = 2500
MAX_TARGET_BYTES = 200 * 1024 * 1024
STARTUP_TIMEOUT_SECONDS = 60
GATEWAY_IMAGE = "python:3.12-alpine"
GATEWAY_PORT = 8081


@dataclass(frozen=True)
class RunningProject:
    migration_id: str
    target_framework: str
    container_id: str
    gateway_container_id: str
    image_tag: str
    network_name: str
    host_port: int
    container_port: int

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.host_port}"


class ProjectRunner:
    """Build target apps on an egress-isolated network and expose a local proxy."""

    GATEWAY_SCRIPT = r'''import http.client, json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
UPSTREAM_HOST, UPSTREAM_PORT = sys.argv[1], int(sys.argv[2])
MAX_BODY, MAX_RESPONSE = 1_000_000, 5_000_000
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *_args): pass
    def do_GET(self): self.forward()
    def do_POST(self): self.forward()
    def forward(self):
        try:
            length = int(self.headers.get("content-length", "0"))
            if length < 0 or length > MAX_BODY:
                return self.reply(413, b'{"detail":"request body too large"}')
            body = self.rfile.read(length) if length else None
            connection = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=12)
            connection.request(self.command, self.path, body=body, headers={
                "Content-Type": self.headers.get("content-type", "application/json"),
                "Accept": self.headers.get("accept", "application/json"),
            })
            upstream = connection.getresponse()
            payload = upstream.read(MAX_RESPONSE + 1)
            status = upstream.status
            content_type = upstream.getheader("Content-Type", "application/json")
            connection.close()
            if len(payload) > MAX_RESPONSE:
                return self.reply(502, b'{"detail":"upstream response too large"}')
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD" and payload:
                self.wfile.write(payload)
        except Exception as exc:
            print("sandbox gateway upstream error:", repr(exc), flush=True)
            self.reply(502, b'{"detail":"target API unavailable"}')
    def reply(self, status, payload):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)
ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
'''

    DOCKERFILES = {
        "spring-boot": (
            "FROM maven:3.8-openjdk-17-slim AS build\n"
            "WORKDIR /workspace\n"
            "COPY pom.xml ./\n"
            "COPY src ./src\n"
            "RUN mvn -B -DskipTests clean package\n"
            "FROM eclipse-temurin:17-jre-alpine\n"
            "WORKDIR /app\n"
            "COPY --from=build /workspace/target/*.jar /app/application.jar\n"
            "EXPOSE 8080\n"
            "USER 10001:10001\n"
            'ENTRYPOINT ["java", "-XX:MaxRAMPercentage=70.0", "-jar", "/app/application.jar"]\n'
        ),
        "go-fiber": (
            "FROM golang:1.22-alpine AS build\n"
            "WORKDIR /workspace\n"
            "COPY go.mod ./\n"
            "COPY . ./\n"
            "RUN go mod download && CGO_ENABLED=0 go build -trimpath -o /lexora ./cmd/server\n"
            "FROM alpine:3.20\n"
            "RUN adduser -D -u 10001 lexora\n"
            "COPY --from=build /lexora /usr/local/bin/lexora\n"
            "EXPOSE 3000\n"
            "USER 10001:10001\n"
            'ENTRYPOINT ["/usr/local/bin/lexora"]\n'
        ),
        "node": (
            "FROM node:18-alpine\n"
            "WORKDIR /app\n"
            "COPY package*.json ./\n"
            "RUN npm install --omit=dev --ignore-scripts\n"
            "COPY . ./\n"
            "RUN chown -R node:node /app\n"
            "EXPOSE 3000\n"
            "USER node\n"
            'CMD ["npm", "start"]\n'
        ),
    }
    PORTS = {"spring-boot": 8080, "go-fiber": 3000, "node": 3000}

    def __init__(self, docker_client: Any | None = None) -> None:
        self.client = docker_client
        self.connection_error: str | None = None
        self._running: dict[str, RunningProject] = {}
        self._embedded_servers: dict[str, Any] = {}
        self._lock = threading.RLock()
        if self.client is None:
            if docker is None:
                self.connection_error = "Docker SDK is not installed."
            else:
                try:
                    self.client = docker.from_env(timeout=5)
                    self.client.ping()
                except Exception as exc:
                    self.connection_error = f"Docker daemon is unavailable: {exc}"
                    self.client = None
                    logger.warning(self.connection_error)

    def deploy_target_project(self, migration_id: str, target_framework: str) -> RunningProject:
        """Build the target, isolate it, and expose it through a loopback gateway."""
        migration_id = self._validated_migration_id(migration_id)
        framework = self.normalize_runtime_framework(target_framework)
        
        # Check primary target directory, or fallback to fine-tuned Qwen target directory
        target_root = (OUTPUT_ROOT / migration_id / "target").resolve()
        if not target_root.is_dir():
            target_root = (OUTPUT_ROOT / migration_id / "target-qwen-finetuned").resolve()

        if not target_root.is_relative_to(OUTPUT_ROOT.resolve()) or not target_root.is_dir():
            raise FileNotFoundError("Completed target project was not found")

        self._validate_target_tree(target_root, framework)

        # Check if Docker daemon is active and accessible
        use_docker = False
        try:
            self._ensure_docker_client()
            use_docker = self.client is not None
        except Exception as exc:
            logger.info("Docker daemon not reachable (%s); activating local embedded runtime sandbox", exc)
            use_docker = False

        with self._lock:
            self.stop_project(migration_id)

            if not use_docker:
                # Embedded local sandbox engine for development and environments without active Docker daemon
                host_port = self._find_available_host_port()
                server = self._start_embedded_sandbox(migration_id, host_port, framework, target_root)
                deployment = RunningProject(
                    migration_id=migration_id,
                    target_framework=framework,
                    container_id=f"embedded-proc-{migration_id[:8]}",
                    gateway_container_id=f"embedded-gw-{migration_id[:8]}",
                    image_tag="lexora/embedded-sandbox:local",
                    network_name="local-loopback",
                    host_port=host_port,
                    container_port=host_port,
                )
                self._embedded_servers[migration_id] = server
                self._running[migration_id] = deployment
                return deployment

            dockerfile = target_root / "Dockerfile"
            dockerfile.write_text(self.DOCKERFILES[framework], encoding="utf-8")
            if framework == "go-fiber":
                self._pin_go_dependencies(target_root)
            image_tag = f"lexora/project-{migration_id.lower()}:latest"
            network_name = f"lexora-run-{migration_id.lower()}"
            container_port = self.PORTS[framework]
            container = None
            gateway = None
            network = None
            try:
                build_logs = self.client.api.build(
                    path=str(target_root),
                    tag=image_tag,
                    dockerfile="Dockerfile",
                    rm=True,
                    forcerm=True,
                    pull=True,
                    decode=True,
                    container_limits={
                        "memory": 2 * 1024 * 1024 * 1024,
                        "memswap": 2 * 1024 * 1024 * 1024,
                        "cpushares": 512,
                    },
                )
                self._consume_build_logs(build_logs)
                network = self.client.networks.create(
                    network_name,
                    driver="bridge",
                    internal=True,
                    labels={"lexora.migration_id": migration_id},
                )
                target_name = f"lexora-target-{migration_id.lower()}"
                container = self.client.containers.run(
                    image_tag,
                    detach=True,
                    name=target_name,
                    network=network.name,
                    labels={"lexora.migration_id": migration_id},
                    mem_limit="768m",
                    memswap_limit="768m",
                    cpu_period=100000,
                    cpu_quota=100000,
                    pids_limit=128,
                    read_only=True,
                    tmpfs={"/tmp": "rw,noexec,nosuid,size=32m"},
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                    restart_policy={"Name": "no"},
                    init=True,
                )
                self._ensure_gateway_image()
                gateway = self.client.containers.run(
                    GATEWAY_IMAGE,
                    command=[
                        "python", "-u", "-c", self.GATEWAY_SCRIPT,
                        target_name, str(container_port),
                    ],
                    detach=True,
                    name=f"{network_name}-gateway",
                    labels={"lexora.migration_id": migration_id, "lexora.role": "proxy"},
                    ports={f"{GATEWAY_PORT}/tcp": ("127.0.0.1", self._find_available_host_port())},
                    mem_limit="128m",
                    memswap_limit="128m",
                    cpu_period=100000,
                    cpu_quota=50000,
                    pids_limit=32,
                    read_only=True,
                    tmpfs={"/tmp": "rw,noexec,nosuid,size=8m"},
                    user="65534:65534",
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                    restart_policy={"Name": "no"},
                    init=True,
                )
                network.connect(gateway, aliases=["lexora-proxy"])
                host_port = self._mapped_host_port(gateway, GATEWAY_PORT)
                deployment = RunningProject(
                    migration_id=migration_id,
                    target_framework=framework,
                    container_id=container.id,
                    gateway_container_id=gateway.id,
                    image_tag=image_tag,
                    network_name=network.name,
                    host_port=host_port,
                    container_port=container_port,
                )
                self._wait_until_ready(deployment, container)
                self._running[migration_id] = deployment
                return deployment
            except Exception:
                if gateway is not None:
                    self._remove_container(gateway)
                if container is not None:
                    self._remove_container(container)
                if network is not None:
                    self._remove_network(network)
                raise

    def _ensure_docker_client(self) -> None:
        """Reconnect at deployment time if Docker Desktop started after Uvicorn."""
        if docker is None:
            self.connection_error = "Docker SDK is not installed; install requirements.txt."
            raise RuntimeError(self.connection_error)
        if self.client is not None:
            try:
                self.client.ping()
                return
            except Exception:
                try:
                    self.client.close()
                except Exception:
                    pass
                self.client = None
        try:
            self.client = docker.from_env(timeout=10)
            self.client.ping()
            self.connection_error = None
        except Exception as exc:
            self.client = None
            self.connection_error = f"Docker daemon is unavailable: {exc}"
            raise RuntimeError(self.connection_error) from exc

    def get_deployment(self, migration_id: str) -> RunningProject | None:
        with self._lock:
            return self._running.get(migration_id)

    def stop_project(self, migration_id: str) -> None:
        deployment = self._running.pop(migration_id, None)
        if deployment is None or self.client is None:
            return
        try:
            container = self.client.containers.get(deployment.container_id)
            container.stop(timeout=3)
            container.remove(force=True)
        except Exception:
            logger.info("Sandbox container %s was already stopped", migration_id, exc_info=True)
        try:
            gateway = self.client.containers.get(deployment.gateway_container_id)
            gateway.stop(timeout=3)
            gateway.remove(force=True)
        except Exception:
            logger.info("Sandbox gateway %s was already stopped", migration_id, exc_info=True)
        try:
            self.client.networks.get(deployment.network_name).remove()
        except Exception:
            logger.info("Sandbox network %s was already removed", migration_id, exc_info=True)

    def shutdown(self) -> None:
        for migration_id in list(self._running):
            self.stop_project(migration_id)
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                logger.debug("Could not close Docker client", exc_info=True)

    @classmethod
    def _validate_target_tree(cls, root: Path, framework: str) -> None:
        required = {
            "spring-boot": ("pom.xml", "src/main/java"),
            "go-fiber": ("go.mod", "cmd/server"),
            "node": ("package.json", "package.json"),
        }[framework]
        if not (root / required[0]).is_file() or not (root / required[1]).exists():
            raise ValueError(f"Target project is missing required {framework} build files")
        total_size = 0
        file_count = 0
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("Symlinks are not allowed in a target project sandbox")
            if path.is_file():
                file_count += 1
                total_size += path.stat().st_size
                if file_count > MAX_TARGET_FILES or total_size > MAX_TARGET_BYTES:
                    raise ValueError("Target project exceeds sandbox build limits")

    @staticmethod
    def normalize_runtime_framework(value: str) -> str:
        aliases = {
            "spring": "spring-boot", "springboot": "spring-boot", "spring-boot": "spring-boot",
            "go": "go-fiber", "fiber": "go-fiber", "go-fiber": "go-fiber",
            "node": "node", "nodejs": "node", "express": "node", "node-express": "node",
        }
        normalized = aliases.get(value.strip().lower())
        if normalized not in ProjectRunner.DOCKERFILES:
            raise ValueError("Unsupported sandbox target. Choose spring-boot, go-fiber, or node.")
        return normalized

    @staticmethod
    def _pin_go_dependencies(root: Path) -> None:
        """Replace the translator's placeholder `latest` versions with stable pins."""
        go_mod = root / "go.mod"
        pins = {
            "github.com/gofiber/fiber/v2": "v2.52.5",
            "go.mongodb.org/mongo-driver": "v1.14.0",
            "github.com/golang-jwt/jwt/v5": "v5.2.1",
            "golang.org/x/crypto": "v0.21.0",
        }
        lines = go_mod.read_text(encoding="utf-8").splitlines()
        rewritten = []
        for line in lines:
            match = re.match(r"^(\s*)(\S+)\s+latest(\s*(?://.*)?)$", line)
            if match:
                module = match.group(2)
                if module not in pins:
                    raise ValueError(f"No safe pinned version is configured for Go module {module}")
                line = f"{match.group(1)}{module} {pins[module]}{match.group(3)}"
            rewritten.append(line)
        go_mod.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    @staticmethod
    def _validated_migration_id(value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError) as exc:
            raise ValueError("migration_id must be a valid UUID") from exc

    @staticmethod
    def _mapped_host_port(container: Any, container_port: int) -> int:
        port_key = f"{container_port}/tcp"
        # Docker Desktop can populate NetworkSettings.Ports shortly after
        # containers.run returns, so refresh briefly before treating it as an
        # actual publish failure.
        for attempt in range(5):
            container.reload()
            binding = (container.attrs.get("NetworkSettings", {}).get("Ports") or {}).get(
                port_key
            )
            if binding and binding[0].get("HostPort"):
                return int(binding[0]["HostPort"])
            if attempt < 4:
                time.sleep(0.2)
        raise RuntimeError(
            "Docker did not publish sandbox port "
            f"{port_key}; reported bindings: "
            f"{container.attrs.get('NetworkSettings', {}).get('Ports')}"
        )

    @staticmethod
    def _find_available_host_port() -> int:
        """Ask the OS for an available ephemeral TCP port on IPv4 loopback."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _ensure_gateway_image(self) -> None:
        try:
            self.client.images.get(GATEWAY_IMAGE)
        except Exception:
            logger.info("Pulling local sandbox gateway image %s", GATEWAY_IMAGE)
            self.client.images.pull(GATEWAY_IMAGE)

    @staticmethod
    def _wait_until_ready(deployment: RunningProject, container: Any) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        with httpx.Client(timeout=1.0, trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get(deployment.base_url + "/")
                    # A 404 still proves the target API process is answering HTTP.
                    if response.status_code < 500:
                        return
                except httpx.HTTPError:
                    pass
                container.reload()
                if not container.attrs.get("State", {}).get("Running", True):
                    logs = container.logs(tail=80).decode("utf-8", errors="replace")
                    raise RuntimeError(f"Target container exited during startup: {logs[-4000:]}")
                time.sleep(0.5)
        raise TimeoutError("Target API did not become ready within 60 seconds")

    @staticmethod
    def _consume_build_logs(log_stream: Any) -> None:
        errors: list[str] = []
        for item in log_stream:
            if "error" in item:
                errors.append(str(item["error"]))
            elif "errorDetail" in item:
                errors.append(str(item["errorDetail"].get("message", item["errorDetail"])))
        if errors:
            raise RuntimeError("Docker image build failed: " + "\n".join(errors)[-4000:])

    @staticmethod
    def _remove_container(container: Any) -> None:
        try:
            container.remove(force=True)
        except Exception:
            logger.warning("Unable to remove failed sandbox container", exc_info=True)

    @staticmethod
    def _remove_network(network: Any) -> None:
        try:
            network.remove()
        except Exception:
            logger.warning("Unable to remove failed sandbox network", exc_info=True)


project_runner = ProjectRunner()


def deploy_target_project(migration_id: str, target_framework: str) -> RunningProject:
    """Convenience function for the configured process-wide runner."""
    return project_runner.deploy_target_project(migration_id, target_framework)
