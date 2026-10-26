from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers.analyze import router as analyze_router
from backend.routers.compile import router as compile_router
from backend.routers.execute import router as execute_router
from backend.routers.health import router as health_router
from backend.routers.migrate import router as migrate_router
from backend.routers.project import router as project_router
from backend.utils.db import close_mongo_connection, connect_to_mongo
from backend.services.project_runner import project_runner

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await connect_to_mongo()
    try:
        yield
    finally:
        await asyncio.to_thread(project_runner.shutdown)
        await close_mongo_connection()


app = FastAPI(title="Lexora API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router, prefix="/api")
app.include_router(analyze_router, prefix="/api")
app.include_router(migrate_router, prefix="/api")
app.include_router(compile_router, prefix="/api")
app.include_router(project_router, prefix="/api")
app.include_router(execute_router, prefix="/api")
