"""Run generated Python files in disposable, constrained Docker containers."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from backend.models.schemas import CompilationResult

try:
    import docker
except ModuleNotFoundError:  # Keep API startup available when Docker SDK is absent.
    docker = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = (PROJECT_ROOT / "outputs").resolve()
IMAGE_BY_LANGUAGE = {"python": "python:3.10-alpine"}


class DockerSandboxCompiler:
    def __init__(self) -> None:
        self.docker_client: Any | None = None
        self.connection_error: str | None = None
        self.last_cleanup_confirmed = False
        if docker is None:
            self.connection_error = "Docker SDK is not installed; install requirements.txt."
            return
        try:
            client = docker.from_env(timeout=3)
            client.ping()
            self.docker_client = client
        except docker.errors.DockerException as exc:
            self.connection_error = f"Docker daemon is unavailable: {exc}"
            try:
                client.close()  # type: ignore[possibly-undefined]
            except Exception:
                pass
            logger.warning(self.connection_error)

    def compile_and_run_file(
        self,
        file_path: str,
        target_lang: str = "python",
        timeout_seconds: int = 5,
    ) -> CompilationResult:
        self.last_cleanup_confirmed = False
        candidate = Path(file_path).resolve()
        try:
            candidate.relative_to(OUTPUT_ROOT)
        except ValueError as exc:
            raise ValueError("Compilation file must be located inside outputs/") from exc
        if not candidate.is_file():
            raise FileNotFoundError(f"Compilation file does not exist: {candidate}")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        image = IMAGE_BY_LANGUAGE.get(target_lang.lower())
        if image is None:
            raise ValueError(f"Unsupported compilation target: {target_lang}")

        migration_id, model_name = self._identify_artifact(candidate)
        if self.docker_client is None:
            return CompilationResult(
                migration_id=migration_id,
                model_name=model_name,
                status="FAILED",
                stdout="",
                stderr=self.connection_error or "Docker daemon is unavailable.",
                execution_time_seconds=0.0,
                error_type="DockerUnavailable",
            )

        container = None
        started = time.perf_counter()
        stdout = ""
        stderr = ""
        error_type = "None"
        status = "FAILED"
        try:
            container = self.docker_client.containers.run(
                image=image,
                command=["python", "-B", "/app/code.py"],
                volumes={
                    str(candidate): {"bind": "/app/code.py", "mode": "ro"}
                },
                network_mode="none",
                mem_limit="256m",
                memswap_limit="256m",
                cpu_period=100000,
                cpu_quota=50000,
                pids_limit=64,
                read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=16m"},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                user="65534:65534",
                log_config={
                    "type": "json-file",
                    "config": {"max-size": "1m", "max-file": "1"},
                },
                detach=True,
                remove=False,
            )
            timed_out = False
            try:
                wait_result = container.wait(timeout=timeout_seconds)
                exit_code = int(wait_result.get("StatusCode", 1))
            except Exception as exc:
                if self._is_timeout_exception(exc):
                    timed_out = True
                    error_type = "TimeoutError"
                    try:
                        container.kill()
                    except Exception:
                        logger.warning("Could not kill timed out sandbox", exc_info=True)
                    exit_code = -1
                else:
                    raise

            stdout = self._decode_logs(container.logs(stdout=True, stderr=False))
            stderr = self._decode_logs(container.logs(stdout=False, stderr=True))
            elapsed = time.perf_counter() - started
            if timed_out:
                timeout_message = f"Execution timed out after {timeout_seconds} seconds."
                stderr = f"{stderr.rstrip()}\n{timeout_message}".strip()
            elif stderr.strip():
                status = "FAILED"
                error_type = self._extract_exception_type(stderr) or "RuntimeError"
            elif exit_code == 0:
                status = "SUCCESS"
                error_type = "None"
            else:
                status = "FAILED"
                error_type = "ExitCodeError"
                if not stderr:
                    stderr = f"Program exited with status code {exit_code}."
            return CompilationResult(
                migration_id=migration_id,
                model_name=model_name,
                status=status,
                stdout=stdout,
                stderr=stderr,
                execution_time_seconds=elapsed,
                error_type=error_type,
            )
        except Exception as exc:
            docker_exception = docker.errors.DockerException if docker is not None else ()
            if docker_exception and isinstance(exc, docker_exception):
                logger.exception("Docker sandbox execution failed")
                return CompilationResult(
                    migration_id=migration_id,
                    model_name=model_name,
                    status="FAILED",
                    stdout=stdout,
                    stderr=f"Docker execution failed: {exc}",
                    execution_time_seconds=time.perf_counter() - started,
                    error_type="DockerError",
                )
            raise
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                    self.last_cleanup_confirmed = True
                except Exception:
                    logger.exception("Failed to remove sandbox container")
                    self.last_cleanup_confirmed = False

    @staticmethod
    def _decode_logs(value: bytes | str) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").strip()
        return str(value).strip()

    @staticmethod
    def _is_timeout_exception(exc: Exception) -> bool:
        return isinstance(exc, TimeoutError) or exc.__class__.__name__ in {
            "ReadTimeout",
            "ConnectTimeout",
            "Timeout",
        }

    @staticmethod
    def _extract_exception_type(stderr: str) -> str | None:
        for line in reversed(stderr.strip().splitlines()):
            match = re.match(r"^([A-Za-z_]\w*(?:Error|Exception))(?::|$)", line.strip())
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _identify_artifact(file_path: Path) -> tuple[str, str]:
        stem = file_path.stem
        if stem.endswith("_output"):
            stem = stem[: -len("_output")]
        aliases = {"openai_gpt_oss_20b": "openai/gpt-oss-20b"}
        return file_path.parent.name, aliases.get(stem, stem)
