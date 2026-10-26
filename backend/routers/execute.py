"""Local target deployment and constrained HTTP reverse proxy APIs."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

from backend.models.schemas import ApiProxyRequest, ProjectDeployRequest, ProjectDeployResponse
from backend.services.project_runner import ProjectRunner, project_runner
from backend.utils.db import get_projects_collection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/project", tags=["Interactive API Sandbox"])
PROXY_TIMEOUT_SECONDS = 15.0
MAX_PROXY_BODY_BYTES = 1_000_000
MAX_PROXY_RESPONSE_BYTES = 5_000_000


@router.post("/deploy/{migration_id}", response_model=ProjectDeployResponse)
async def deploy_project(
    migration_id: str, request: ProjectDeployRequest
) -> ProjectDeployResponse:
    try:
        migration_id = str(uuid.UUID(migration_id))
        framework = ProjectRunner.normalize_runtime_framework(request.target_framework)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    collection = get_projects_collection()
    project = await collection.find_one({"migration_id": migration_id})
    if not project or project.get("status") not in {"COMPLETED", "PARTIAL"}:
        raise HTTPException(status_code=409, detail="Finish the project migration before deployment")
    if project.get("target_framework") != framework:
        raise HTTPException(status_code=409, detail="Target framework does not match this migration")

    try:
        deployment = await asyncio.to_thread(
            project_runner.deploy_target_project, migration_id, framework
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Sandbox deployment failed for migration %s", migration_id)
        detail = str(exc).strip() or type(exc).__name__
        if len(detail) > 800:
            detail = detail[:797] + "..."
        await collection.update_one(
            {"migration_id": migration_id},
            {"$set": {"sandbox_status": "FAILED", "sandbox_error": detail}},
        )
        raise HTTPException(status_code=503, detail=f"Sandbox deployment failed: {detail}") from exc

    await collection.update_one(
        {"migration_id": migration_id},
        {"$set": {
            "sandbox_status": "RUNNING",
            "sandbox_target_framework": framework,
            "sandbox_container_id": deployment.container_id,
            "sandbox_host_port": deployment.host_port,
            "sandbox_started_at": time.time(),
        }},
    )
    return ProjectDeployResponse(
        migration_id=migration_id,
        status="RUNNING",
        target_framework=framework,
        host_port=deployment.host_port,
        base_url=deployment.base_url,
    )


@router.post("/proxy/{migration_id}")
async def proxy_project_request(migration_id: str, request: ApiProxyRequest) -> Response:
    try:
        migration_id = str(uuid.UUID(migration_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="migration_id must be a valid UUID") from exc
    deployment = project_runner.get_deployment(migration_id)
    if deployment is None:
        raise HTTPException(status_code=409, detail="Deploy this migration to the local sandbox first")

    route = request.route.strip()
    parsed_route = urlsplit(route)
    decoded_path = parsed_route.path
    # Servers/frameworks may decode percent escapes more than once. Inspect a
    # bounded number of rounds so encoded dot segments cannot escape routing.
    for _ in range(4):
        next_path = unquote(decoded_path)
        if next_path == decoded_path:
            break
        decoded_path = next_path
    if (
        not route.startswith("/")
        or route.startswith("//")
        or "\\" in route
        or "\\" in decoded_path
        or any(ord(char) < 32 for char in route)
        or "://" in route
        or parsed_route.scheme
        or parsed_route.netloc
        or parsed_route.fragment
        or any(segment == ".." for segment in decoded_path.split("/"))
    ):
        raise HTTPException(status_code=400, detail="route must be a relative path on the deployed API")

    body_bytes = json.dumps(request.body, separators=(",", ":")).encode("utf-8")
    if len(body_bytes) > MAX_PROXY_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body exceeds the 1 MB sandbox limit")
    url = deployment.base_url + route
    try:
        async with httpx.AsyncClient(
            timeout=PROXY_TIMEOUT_SECONDS,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            async with client.stream(
                request.method,
                url,
                json=request.body if request.method == "POST" else None,
            ) as upstream:
                status_code = upstream.status_code
                chunks: list[bytes] = []
                total_bytes = 0
                async for chunk in upstream.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > MAX_PROXY_RESPONSE_BYTES:
                        raise HTTPException(status_code=502, detail="Sandbox response exceeds the 5 MB proxy limit")
                    chunks.append(chunk)
                upstream_content = b"".join(chunks)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Sandbox API request timed out") from exc
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        logger.warning("Sandbox proxy could not reach migration %s: %s", migration_id, exc)
        raise HTTPException(status_code=502, detail="Could not reach the deployed target API") from exc

    if status_code == 204:
        return Response(status_code=204)
    try:
        return JSONResponse(content=json.loads(upstream_content), status_code=status_code)
    except (ValueError, UnicodeDecodeError):
        pass
    return JSONResponse(
        content={"raw": upstream_content.decode("utf-8", errors="replace")},
        status_code=status_code,
    )
