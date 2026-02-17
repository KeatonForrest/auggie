"""Watchlist web routes — manage recurring research."""

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from auth import require_onboarding, get_current_user
from database import (
    get_user_usage,
    list_watchlist_items, create_watchlist_item, get_watchlist_item,
    update_watchlist_item, delete_watchlist_item, get_score_history,
    get_watchlist_item_by_url, count_significant_changes, mark_changes_seen,
)
from api.validation import validate_company_url
from routes._helpers import templates

router = APIRouter()


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(request: Request, user: dict = Depends(require_onboarding)):
    """Watchlist management page."""
    usage = await get_user_usage(user["id"])
    items, _has_more = await list_watchlist_items(user["id"])
    await mark_changes_seen(user["id"])

    # Fetch recent score history per item
    items_with_history = []
    for item in items:
        history = await get_score_history(item["id"], user["id"], limit=5)
        item["history"] = history
        items_with_history.append(item)

    return templates.TemplateResponse(
        request,
        "watchlist.html",
        {
            "user": user,
            "items": items_with_history,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
        },
    )


@router.post("/watchlist/add")
async def watchlist_add(
    request: Request,
    user: dict = Depends(require_onboarding),
    company_url: str = Form(...),
    company_name: str = Form(None),
    schedule: str = Form("biweekly"),
):
    """Add a company to the watchlist (form POST from web UI)."""
    if schedule not in ("weekly", "biweekly", "monthly"):
        schedule = "biweekly"

    try:
        company_url = validate_company_url(company_url)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid company URL")

    await create_watchlist_item(user["id"], company_url, company_name, schedule)
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/{item_id}/update")
async def watchlist_update(
    item_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
    schedule: str = Form(None),
    status: str = Form(None),
):
    """Update a watchlist item (form POST)."""
    if schedule and schedule not in ("weekly", "biweekly", "monthly"):
        schedule = None
    if status and status not in ("active", "paused"):
        status = None

    item = await update_watchlist_item(item_id, user["id"], schedule, status)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return RedirectResponse(url="/watchlist", status_code=303)


@router.post("/watchlist/{item_id}/delete")
async def watchlist_delete(
    item_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Remove from watchlist (form POST)."""
    await delete_watchlist_item(item_id, user["id"])
    return RedirectResponse(url="/watchlist", status_code=303)


@router.get("/watchlist/{item_id}/history-json")
async def watchlist_history_json(
    item_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """JSON endpoint for score history (used by expandable rows)."""
    item = await get_watchlist_item(item_id, user["id"])
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    history = await get_score_history(item_id, user["id"])
    return JSONResponse({
        "changes": [
            {
                "old_document_id": h["old_document_id"],
                "new_document_id": h["new_document_id"],
                "old_scores": {
                    "opportunity": h["old_opportunity_score"],
                    "pain": h["old_pain_score"],
                    "fit": h["old_fit_score"],
                    "timing": h["old_timing_score"],
                },
                "new_scores": {
                    "opportunity": h["new_opportunity_score"],
                    "pain": h["new_pain_score"],
                    "fit": h["new_fit_score"],
                    "timing": h["new_timing_score"],
                },
                "is_significant": h["is_significant"],
                "created_at": h["created_at"].isoformat(),
            }
            for h in history
        ]
    })


@router.get("/watchlist/badge")
async def watchlist_badge(request: Request):
    """Lightweight JSON endpoint returning count of recent significant changes."""
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"count": 0})
    count = await count_significant_changes(user["id"])
    return JSONResponse({"count": count})
