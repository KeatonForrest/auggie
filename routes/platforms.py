"""Platforms hub and integration guide routes."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from auth import get_current_user, require_onboarding
from database import get_user_usage
from routes._helpers import templates

router = APIRouter()


@router.get("/platforms", response_class=HTMLResponse)
async def platforms_page(request: Request, user: dict = Depends(require_onboarding)):
    """Platforms hub page with links to integration guides."""
    usage = await get_user_usage(user["id"])
    return templates.TemplateResponse(
        "platforms.html",
        {
            "request": request,
            "user": user,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
        },
    )


@router.get("/guides/clay-pain-based-outbound", response_class=HTMLResponse)
async def guide_clay_pain_outbound_redirect():
    """Redirect old URL to new one."""
    return RedirectResponse(url="/guides/clay-problem-signal-prospecting", status_code=301)


@router.get("/guides/clay-problem-signal-prospecting", response_class=HTMLResponse)
async def guide_clay_problem_signal(request: Request):
    """Clay problem-signal prospecting guide page."""
    user = await get_current_user(request)
    clay_template = {
        "columns": [
            {"name": "Company Website", "type": "text", "description": "The company domain to research"},
            {
                "name": "Auggie Research",
                "type": "http_request",
                "config": {
                    "method": "POST",
                    "url": "https://auggie.app/v1/clay/enrich",
                    "headers": {
                        "Authorization": "Bearer aug_your_key",
                        "Content-Type": "application/json"
                    },
                    "body": "{\"company_url\": \"{{/Company Website}}\"}"
                }
            },
            {"name": "Pain Score", "type": "extract", "path": "pain_score"},
            {"name": "Composite Score", "type": "extract", "path": "composite_score"},
            {"name": "Score Summary", "type": "extract", "path": "score_summary"},
            {"name": "Pain Reasons", "type": "extract", "path": "pain_reasons"},
            {"name": "Business Problems", "type": "extract", "path": "business_problems"},
            {"name": "Talking Points", "type": "extract", "path": "talking_points"},
            {"name": "Product Fit", "type": "extract", "path": "product_fit"},
            {"name": "Document ID", "type": "extract", "path": "document_id"}
        ],
        "filters": [
            {"column": "Pain Score", "operator": ">=", "value": 70}
        ]
    }
    return templates.TemplateResponse(
        "guide_clay_pain_outbound.html",
        {"request": request, "user": user, "clay_template_json": clay_template}
    )


@router.get("/guides/n8n", response_class=HTMLResponse)
async def guide_n8n(request: Request):
    user = await get_current_user(request)
    return templates.TemplateResponse("guide_n8n.html", {"request": request, "user": user})


@router.get("/guides/make", response_class=HTMLResponse)
async def guide_make(request: Request):
    user = await get_current_user(request)
    return templates.TemplateResponse("guide_make.html", {"request": request, "user": user})


@router.get("/guides/zapier", response_class=HTMLResponse)
async def guide_zapier(request: Request):
    user = await get_current_user(request)
    return templates.TemplateResponse("guide_zapier.html", {"request": request, "user": user})
