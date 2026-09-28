from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
from services.shared.health import router as health_router
from services.shared.metrics import metrics_middleware
from services.shared.logging import setup_logging
from services.shared.database import db
from services.shared.redis_client import redis_client
from services.api_gateway.routes import router as api_router
from services.api_gateway.middleware import setup_middlewares

logger = setup_logging("api-gateway")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting API Gateway...")
    await db.get_pool()
    await redis_client.get_redis()
    yield
    logger.info("Shutting down API Gateway...")
    await db.close_pool()
    await redis_client.close_redis()

app = FastAPI(title="Aegis API Gateway", lifespan=lifespan)
setup_middlewares(app)
app.middleware("http")(metrics_middleware)

app.include_router(health_router, tags=["Health"])
app.include_router(api_router, prefix="/v1", tags=["API"])
