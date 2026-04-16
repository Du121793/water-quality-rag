from fastapi import APIRouter

from routes.system import router as system_router

router = APIRouter()
router.include_router(system_router, prefix="/system", tags=["system"])
