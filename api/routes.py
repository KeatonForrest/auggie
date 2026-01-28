"""v1 API routes — authenticated via API key."""

from fastapi import APIRouter, Depends

from api.auth import require_api_key

router = APIRouter(prefix="/v1", tags=["v1"])


@router.get("/ping")
async def ping(api_user: dict = Depends(require_api_key)):
    """Health check endpoint. Returns 200 if API key is valid."""
    return {"status": "ok", "user_id": api_user["user_id"]}
