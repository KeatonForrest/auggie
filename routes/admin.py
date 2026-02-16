"""Admin dashboard routes for platform management."""

import logging

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from auth import require_super_admin
from routes._helpers import templates
from db.users import list_all_users_admin, toggle_admin, add_credits, get_user_by_id
from db.task_queue import get_queue_stats, get_failed_tasks, retry_failed_task
from db.orgs import get_all_orgs_stats, get_revenue_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(request: Request, user: dict = Depends(require_super_admin)):
    """Render the admin dashboard."""
    search = request.query_params.get("search", "")
    page = int(request.query_params.get("page", "1"))
    limit = 50
    offset = (page - 1) * limit

    users = await list_all_users_admin(limit=limit, offset=offset, search=search or None)
    queue_stats = await get_queue_stats()
    failed_tasks = await get_failed_tasks(limit=50)
    orgs = await get_all_orgs_stats()
    revenue = await get_revenue_stats()

    return templates.TemplateResponse(request, "admin_dashboard.html", {
        "user": user,
        "users": users,
        "search": search,
        "page": page,
        "queue_stats": queue_stats,
        "failed_tasks": failed_tasks,
        "orgs": orgs,
        "revenue": revenue,
        "is_admin": True,
        "impersonating_as": request.session.get("impersonating_as"),
    })


@router.get("/queue")
async def queue_depth(request: Request, user: dict = Depends(require_super_admin)):
    """Return task queue counts grouped by status (admin only)."""
    stats = await get_queue_stats()
    return JSONResponse(stats)


class AddCreditsRequest(BaseModel):
    amount: int


@router.post("/users/{user_id}/toggle-admin")
async def toggle_user_admin(user_id: int, user: dict = Depends(require_super_admin)):
    """Toggle admin status for a user."""
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot toggle your own admin status")
    new_val = await toggle_admin(user_id)
    return {"is_admin": new_val}


@router.post("/users/{user_id}/add-credits")
async def add_user_credits(user_id: int, body: AddCreditsRequest, user: dict = Depends(require_super_admin)):
    """Add credits to a user's org."""
    if body.amount <= 0 or body.amount > 10000:
        raise HTTPException(status_code=400, detail="Amount must be between 1 and 10000")
    new_balance = await add_credits(user_id, body.amount)
    return {"new_balance_cents": new_balance}


@router.post("/users/{user_id}/impersonate")
async def impersonate_user(request: Request, user_id: int, user: dict = Depends(require_super_admin)):
    """Impersonate a user by swapping session."""
    target = await get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    request.session["original_admin_id"] = user["id"]
    request.session["user_id"] = user_id
    request.session["impersonating_as"] = target.get("email", str(user_id))
    return RedirectResponse(url="/", status_code=303)


@router.post("/stop-impersonation")
async def stop_impersonation(request: Request):
    """Restore original admin session."""
    original_id = request.session.get("original_admin_id")
    if not original_id:
        raise HTTPException(status_code=400, detail="Not impersonating")
    request.session["user_id"] = original_id
    request.session.pop("original_admin_id", None)
    request.session.pop("impersonating_as", None)
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/tasks/{task_id}/retry")
async def retry_task(task_id: int, user: dict = Depends(require_super_admin)):
    """Retry a failed task."""
    success = await retry_failed_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found or not in failed state")
    return {"status": "requeued"}
