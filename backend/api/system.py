from fastapi import APIRouter

from ..services import system

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("")
def get_status():
    return system.status()
