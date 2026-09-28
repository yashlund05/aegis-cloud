from fastapi import FastAPI
from contextlib import asynccontextmanager
from services.shared.health import router as health_router
from services.shared.metrics import metrics_middleware
from services.shared.logging import setup_logging
from services.shared.database import db
from services.shared.redis_client import redis_client
from services.telemetry_collector.routes import router as api_router

logger = setup_logging("telemetry-collector")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Telemetry Collector...")
    await db.get_pool()
    await redis_client.get_redis()
    yield
    logger.info("Shutting down Telemetry Collector...")
    await db.close_pool()
    await redis_client.close_redis()

app = FastAPI(title="Aegis Telemetry Collector", lifespan=lifespan)
app.middleware("http")(metrics_middleware)

app.include_router(health_router, tags=["Health"])
app.include_router(api_router, prefix="/v1", tags=["API"])
