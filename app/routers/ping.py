from fastapi import APIRouter
router = APIRouter(prefix="/ping", tags=["health"])

@router.get("")
def ping():
    return "pong"
