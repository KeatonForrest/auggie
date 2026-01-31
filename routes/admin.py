"""Admin-only routes for operational visibility."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import get_current_user
from database import get_user_usage
from db.task_queue import get_queue_stats

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/queue")
async def queue_depth(request: Request):
    """Return task queue counts grouped by status (admin only)."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    usage = await get_user_usage(user["id"])
    if not usage.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")

    stats = await get_queue_stats()
    return JSONResponse(stats)
