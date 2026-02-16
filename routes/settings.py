"""Settings routes: onboarding, settings, API keys, webhook, materials."""

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
    get_material_preview, get_material,
)
from api.keys import generate_api_key
from routes._helpers import templates, logger, parse_personas_string, get_materials_service

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

    return templates.TemplateResponse(request, "onboarding.html", {"user": user})


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
        request,
        "settings.html",
        {
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
    product_description: str = Form(""),
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
        product_description=product_description,
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
        request,
        "api_keys.html",
        {
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
        request,
        "materials.html",
        {
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
