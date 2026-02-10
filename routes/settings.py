"""Settings routes: onboarding, settings, API keys, webhook, materials, automations."""

import logging
import secrets as _secrets

from fastapi import APIRouter, HTTPException, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from auth import require_auth, require_onboarding
from config import get_settings
from database import (
    update_user_profile, get_user_usage, get_user_materials,
    create_api_key_record, list_api_keys, revoke_api_key, get_api_key_usage_stats,
    get_user_webhook, upsert_webhook, delete_user_webhook,
    get_automation_rules, get_automation_runs, get_integration,
    create_automation_rule, update_automation_rule, delete_automation_rule,
    get_material_preview, get_material,
)
from api.keys import generate_api_key
from routes._helpers import templates, logger, parse_personas_string, get_materials_service
from routes.schemas import AutomationCreateRequest, AutomationToggleRequest

settings = get_settings()
router = APIRouter()


# =============================================================================
# Onboarding
# =============================================================================

@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(request: Request, user: dict = Depends(require_auth)):
    """Onboarding page to collect company info."""
    if user.get("product_context"):
        # Already onboarded, redirect to home
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "onboarding.html",
        {"request": request, "user": user}
    )


@router.post("/onboarding")
async def complete_onboarding(
    request: Request,
    company_name: str = Form(...),
    product_name: str = Form(""),  # Now optional - extracted from materials
    product_description: str = Form(""),  # Now optional - extracted from materials
    problems_solved: str = Form(...),
    differentiators: str = Form(""),  # Now optional - extracted from materials
    target_company_size: list[str] = Form([]),
    target_industries: list[str] = Form([]),
    target_level: list[str] = Form([]),
    target_function: list[str] = Form([]),
    custom_signals: str = Form(""),
    product_type: str = Form("saas"),
    user: dict = Depends(require_auth),
):
    """Save onboarding data and redirect to dashboard."""
    # Join checkbox values into comma-separated strings
    target_size_str = ", ".join(target_company_size) if target_company_size else ""
    target_industries_str = ", ".join(target_industries) if target_industries else ""

    # Combine level + function into personas string
    # e.g., "Levels: VP, Director | Functions: Sales / Revenue, Marketing"
    personas_parts = []
    if target_level:
        personas_parts.append(f"Levels: {', '.join(target_level)}")
    if target_function:
        personas_parts.append(f"Functions: {', '.join(target_function)}")
    target_personas_str = " | ".join(personas_parts) if personas_parts else ""

    await update_user_profile(
        user_id=user["id"],
        company_name=company_name,
        product_name=product_name,
        product_description=product_description,
        problems_solved=problems_solved,
        differentiators=differentiators,
        target_company_size=target_size_str,
        target_industries=target_industries_str,
        target_personas=target_personas_str,
        competitors="",  # No longer collected in onboarding
        product_type=product_type,
        custom_signals=custom_signals,
    )
    return RedirectResponse(url="/", status_code=302)


# =============================================================================
# Settings
# =============================================================================

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    saved: bool = False,
    user: dict = Depends(require_onboarding),
):
    """Settings page to edit profile."""
    # Parse stored values back into lists for checkbox state
    selected_sizes = [s.strip() for s in (user.get("target_company_size") or "").split(", ") if s.strip()]
    selected_industries = [i.strip() for i in (user.get("target_industries") or "").split(", ") if i.strip()]
    selected_levels, selected_functions = parse_personas_string(user.get("target_personas") or "")

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "saved": saved,
            "selected_sizes": selected_sizes,
            "selected_industries": selected_industries,
            "selected_levels": selected_levels,
            "selected_functions": selected_functions,
        }
    )


@router.post("/settings")
async def save_settings(
    request: Request,
    company_name: str = Form(...),
    problems_solved: str = Form(...),
    target_company_size: list[str] = Form([]),
    target_industries: list[str] = Form([]),
    target_level: list[str] = Form([]),
    target_function: list[str] = Form([]),
    custom_signals: str = Form(""),
    product_type: str = Form("saas"),
    user: dict = Depends(require_onboarding),
):
    """Save updated profile settings."""
    # Join checkbox values into comma-separated strings
    target_size_str = ", ".join(target_company_size) if target_company_size else ""
    target_industries_str = ", ".join(target_industries) if target_industries else ""

    # Combine level + function into personas string
    personas_parts = []
    if target_level:
        personas_parts.append(f"Levels: {', '.join(target_level)}")
    if target_function:
        personas_parts.append(f"Functions: {', '.join(target_function)}")
    target_personas_str = " | ".join(personas_parts) if personas_parts else ""

    await update_user_profile(
        user_id=user["id"],
        company_name=company_name,
        product_name=user.get("product_name") or "",
        product_description=user.get("product_description") or "",
        problems_solved=problems_solved,
        differentiators=user.get("differentiators") or "",
        target_company_size=target_size_str,
        target_industries=target_industries_str,
        target_personas=target_personas_str,
        competitors="",
        product_type=product_type,
        custom_signals=custom_signals,
    )
    return RedirectResponse(url="/settings?saved=true", status_code=302)


# =============================================================================
# API Keys Management (UI)
# =============================================================================

@router.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page(request: Request, user: dict = Depends(require_auth)):
    """API keys management page."""
    keys = await list_api_keys(user["id"])
    usage = await get_user_usage(user["id"])
    usage_stats = await get_api_key_usage_stats(user["id"])
    webhook = await get_user_webhook(user["id"])
    return templates.TemplateResponse(
        "api_keys.html",
        {
            "request": request,
            "user": user,
            "api_keys": keys,
            "usage_stats": usage_stats,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "new_key": request.query_params.get("new_key"),
            "webhook": webhook,
            "webhook_secret": request.query_params.get("webhook_secret"),
        }
    )


@router.post("/api-keys/create")
async def create_api_key_route(request: Request, name: str = Form("Default"), user: dict = Depends(require_auth)):
    """Create a new API key."""
    raw_key, key_hash, prefix = generate_api_key()
    await create_api_key_record(user["id"], key_hash, prefix, name)
    return RedirectResponse(url=f"/api-keys?new_key={raw_key}", status_code=303)


@router.post("/api-keys/{key_id}/revoke")
async def revoke_api_key_route(key_id: int, user: dict = Depends(require_auth)):
    """Revoke an API key."""
    await revoke_api_key(key_id, user["id"])
    return RedirectResponse(url="/api-keys", status_code=303)


@router.post("/api-keys/webhook")
async def create_webhook_route(request: Request, webhook_url: str = Form(...), user: dict = Depends(require_auth)):
    """Register a webhook URL."""
    secret = _secrets.token_hex(32)
    await upsert_webhook(user["id"], webhook_url, secret, org_id=user.get("org_id"))
    return RedirectResponse(url=f"/api-keys?webhook_secret={secret}", status_code=303)


@router.post("/api-keys/webhook/delete")
async def delete_webhook_route(user: dict = Depends(require_auth)):
    """Delete user's webhook."""
    await delete_user_webhook(user["id"])
    return RedirectResponse(url="/api-keys", status_code=303)


# =============================================================================
# Materials Endpoints (v2)
# =============================================================================

@router.get("/materials", response_class=HTMLResponse)
async def materials_page(request: Request, user: dict = Depends(require_auth)):
    """Materials management page."""
    if not settings.materials_enabled:
        raise HTTPException(status_code=404, detail="Materials feature not enabled")

    materials = await get_user_materials(user["id"])
    usage = await get_user_usage(user["id"])

    return templates.TemplateResponse(
        "materials.html",
        {
            "request": request,
            "user": user,
            "materials": materials,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
        }
    )


@router.post("/materials/upload")
async def upload_material(
    file: UploadFile = File(...),
    material_type: str = Form("other"),
    user: dict = Depends(require_auth),
):
    """Upload a new material file."""
    if not settings.materials_enabled:
        return JSONResponse({"success": False, "error": "Materials feature not enabled"})

    service = get_materials_service()
    if not service:
        return JSONResponse({"success": False, "error": "Materials service not configured"})

    try:
        material = await service.upload_material(
            user_id=user["id"],
            file=file.file,
            filename=file.filename,
            material_type=material_type
        )
        # Convert datetime to string for JSON serialization
        if material.get("created_at"):
            material["created_at"] = material["created_at"].isoformat()
        if material.get("updated_at"):
            material["updated_at"] = material["updated_at"].isoformat()
        return JSONResponse({"success": True, "material": material})
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)})
    except Exception as e:
        logger.error("Material upload error: %s", e)
        return JSONResponse({"success": False, "error": "Upload failed. Please try again."})


@router.delete("/materials/{material_id}")
async def delete_material(
    material_id: int,
    user: dict = Depends(require_auth),
):
    """Delete a material and its chunks."""
    if not settings.materials_enabled:
        return JSONResponse({"success": False, "error": "Materials feature not enabled"})

    service = get_materials_service()
    if not service:
        return JSONResponse({"success": False, "error": "Materials service not configured"})

    deleted = await service.delete_material(material_id, user["id"])
    return JSONResponse({"success": deleted})


@router.get("/materials/{material_id}/preview")
async def preview_material(
    material_id: int,
    user: dict = Depends(require_auth),
):
    """Return first 5 chunks of a material as preview text."""
    mat = await get_material(material_id, user["id"])
    if not mat:
        raise HTTPException(status_code=404, detail="Material not found")
    if mat["status"] != "ready":
        return JSONResponse({"content": "Material is not ready for preview."})
    content = await get_material_preview(material_id, user["id"])
    return JSONResponse({"content": content})


@router.post("/materials/{material_id}/reprocess")
async def reprocess_material(
    material_id: int,
    user: dict = Depends(require_auth),
):
    """Reprocess a failed material."""
    if not settings.materials_enabled:
        return JSONResponse({"success": False, "error": "Materials feature not enabled"})

    service = get_materials_service()
    if not service:
        return JSONResponse({"success": False, "error": "Materials service not configured"})

    success = await service.reprocess_material(material_id, user["id"])
    return JSONResponse({"success": success})


@router.get("/api/materials")
async def api_list_materials(user: dict = Depends(require_auth)):
    """API: List user's materials."""
    if not settings.materials_enabled:
        return {"materials": [], "enabled": False}

    materials = await get_user_materials(user["id"])
    return {"materials": materials, "enabled": True}


# =============================================================================
# Automation Rules
# =============================================================================

@router.get("/automations", response_class=HTMLResponse)
async def automations_page(request: Request, user: dict = Depends(require_onboarding)):
    """Automation rules management page."""
    rules = await get_automation_rules(user["id"])
    runs = await get_automation_runs(user["id"], limit=50)
    usage = await get_user_usage(user["id"])

    # Check which integrations are connected for action config
    instantly_connected = await get_integration(user["id"], "instantly") is not None
    smartlead_connected = await get_integration(user["id"], "smartlead") is not None
    outreach_connected = await get_integration(user["id"], "outreach") is not None
    salesloft_connected = await get_integration(user["id"], "salesloft") is not None
    slack_connected = await get_integration(user["id"], "slack") is not None

    # Group runs by rule_id for easy lookup in template
    runs_by_rule = {}
    for run in runs:
        runs_by_rule.setdefault(run["rule_id"], []).append(run)

    return templates.TemplateResponse(
        "automations.html",
        {
            "request": request,
            "user": user,
            "rules": rules,
            "runs_by_rule": runs_by_rule,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "instantly_connected": instantly_connected,
            "smartlead_connected": smartlead_connected,
            "outreach_connected": outreach_connected,
            "salesloft_connected": salesloft_connected,
            "slack_connected": slack_connected,
        }
    )


@router.post("/automations")
async def create_automation(request: Request, user: dict = Depends(require_onboarding)):
    """Create a new automation rule."""
    body = AutomationCreateRequest(**(await request.json()))

    name = body.name.strip()
    trigger_event = body.trigger_event
    conditions = body.conditions
    action = body.action
    action_config = body.action_config

    if not name or not trigger_event or not action:
        raise HTTPException(status_code=400, detail="Name, trigger, and action are required")

    valid_triggers = {"list_complete", "account_scored"}
    valid_actions = {"push_instantly", "write_sequences", "notify_slack"}
    if trigger_event not in valid_triggers:
        raise HTTPException(status_code=400, detail=f"Invalid trigger: {trigger_event}")
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    rule = await create_automation_rule(
        user["id"], name, trigger_event, conditions, action, action_config,
    )
    return JSONResponse({"success": True, "rule_id": rule["id"]})


@router.post("/automations/{rule_id}/toggle")
async def toggle_automation(rule_id: int, request: Request, user: dict = Depends(require_onboarding)):
    """Enable or disable an automation rule."""
    body = AutomationToggleRequest(**(await request.json()))
    enabled = body.enabled
    result = await update_automation_rule(rule_id, user["id"], enabled=enabled)
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found")
    return JSONResponse({"success": True})


@router.post("/automations/{rule_id}/delete")
async def delete_automation(rule_id: int, user: dict = Depends(require_onboarding)):
    """Delete an automation rule."""
    deleted = await delete_automation_rule(rule_id, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return JSONResponse({"success": True})
