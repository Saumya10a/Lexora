from datetime import datetime, timezone

from fastapi import APIRouter

from backend.config import settings
from backend.models.schemas import HealthResponse
from backend.utils.db import check_mongo_connection

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health() -> HealthResponse:
    database_connected = await check_mongo_connection()
    return HealthResponse(
        status="ok" if database_connected else "degraded",
        database_connected=database_connected,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
    )
