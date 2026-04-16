from fastapi import APIRouter

from methods.infra.system_health import get_system_health_snapshot

router = APIRouter()


@router.get("/health")
async def health_check():
    return {
        "success": True,
        "data": await get_system_health_snapshot(),
    }
