from fastapi import APIRouter

from routes.rag import router as rag_router
from routes.system import router as system_router

router = APIRouter()
router.include_router(system_router, prefix="/system", tags=["system"])
router.include_router(rag_router, prefix="/rag", tags=["rag"])
