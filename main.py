from contextlib import asynccontextmanager

from fastapi import FastAPI

from methods.base.logger import error, info
from methods.infra.database import close_database_pools, initialize_database_pools
from methods.infra.redis_client import close_redis_client, initialize_redis_client
from routes.index import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理服務啟動與關閉時的共用資源。"""

    try:
        await initialize_database_pools()
        await initialize_redis_client()
        info("系統", "FastAPI 服務啟動完成")
        yield
    except Exception as err:
        error("系統啟動", err)
        raise
    finally:
        await close_redis_client()
        await close_database_pools()
        info("系統", "服務已關閉")


app = FastAPI(
    title="Fish Healthy Prediction AI Helper",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "success": True,
        "message": "AI Helper 服務運作中",
    }
