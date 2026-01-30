"""Team routes: team settings, invite, remove, role change, revoke invite, usage dashboard, invite landing."""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from auth import get_current_user, require_onboarding, require_org_admin
from database import get_user_usage
from routes._helpers import templates, logger

router = APIRouter()


@router.get("/settings/team", response_class=HTMLResponse)
async def team_settings(
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Team settings page — members, invites, invite form."""
    from database import get_org_members, get_pending_invites, get_org
    org_id = user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="No organization found")

    org = await get_org(org_id)
    members = await get_org_members(org_id)
    invites = await get_pending_invites(org_id) if user.get("org_role") == "admin" else []
    usage = await get_user_usage(user["id"])

    return templates.TemplateResponse(
        "team_settings.html",
        {
            "request": request,
            "user": user,
            "org": org,
            "members": members,
            "invites": invites,
            "is_admin": user.get("org_role") == "admin",
            "credits": usage.get("bonus_credits", 0) / 100,
        }
    )


@router.post("/settings/team/invite")
async def team_invite(
    request: Request,
    email: str = Form(...),
    role: str = Form("member"),
    user: dict = Depends(require_org_admin),
):
    """Send team invite (admin only)."""
    from database import create_org_invite
    if role not in ("admin", "member", "viewer"):
        role = "member"
    invite = await create_org_invite(user["org_id"], email, role, user["id"])
    return RedirectResponse(url=f"/settings/team?invited={email}", status_code=302)


@router.post("/settings/team/remove")
async def team_remove(
    request: Request,
    member_id: int = Form(...),
    user: dict = Depends(require_org_admin),
):
    """Remove a team member (admin only)."""
    from database import remove_org_member
    if member_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")
    await remove_org_member(user["org_id"], member_id)
    return RedirectResponse(url="/settings/team", status_code=302)


@router.post("/settings/team/role")
async def team_change_role(
    request: Request,
    member_id: int = Form(...),
    role: str = Form(...),
    user: dict = Depends(require_org_admin),
):
    """Change team member role (admin only)."""
    from database import update_member_role
    if member_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    if role not in ("admin", "member", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")
    await update_member_role(user["org_id"], member_id, role)
    return RedirectResponse(url="/settings/team", status_code=302)


@router.post("/settings/team/revoke-invite")
async def team_revoke_invite(
    request: Request,
    invite_id: int = Form(...),
    user: dict = Depends(require_org_admin),
):
    """Revoke a pending invite (admin only)."""
    from database import revoke_invite
    await revoke_invite(invite_id, user["org_id"])
    return RedirectResponse(url="/settings/team", status_code=302)


@router.get("/invite/{token}", response_class=HTMLResponse)
async def invite_landing(request: Request, token: str):
    """Landing page for invite links."""
    from database import get_invite_by_token
    invite = await get_invite_by_token(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found or expired")
    if invite.get("accepted_at"):
        raise HTTPException(status_code=400, detail="Invite already accepted")
    if invite["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invite has expired")

    user = await get_current_user(request)
    return templates.TemplateResponse(
        "invite_accept.html",
        {
            "request": request,
            "user": user,
            "invite": invite,
            "token": token,
        }
    )


@router.post("/invite/{token}/accept")
async def accept_invite_route(request: Request, token: str):
    """Accept an invite."""
    from database import accept_invite, user_has_data
    user = await get_current_user(request)
    if not user:
        # Store token and redirect to login
        request.session["pending_invite"] = token
        return RedirectResponse(url="/auth/login", status_code=302)

    # Check if user has data in their solo org
    has_data = await user_has_data(user["id"])
    if has_data and user.get("org_id"):
        # User has data - block for now
        raise HTTPException(
            status_code=400,
            detail="You have existing research data. Please contact support to transfer your data before joining a team."
        )

    result = await accept_invite(token, user["id"])
    if not result:
        raise HTTPException(status_code=400, detail="Invite is invalid or expired")

    return RedirectResponse(url="/?joined_team=true", status_code=302)


@router.get("/settings/team/usage", response_class=HTMLResponse)
async def team_usage_dashboard(
    request: Request,
    user: dict = Depends(require_org_admin),
):
    """Per-member usage breakdown (admin only)."""
    from database import get_org_usage_breakdown, get_org, get_all_feedback
    org_id = user.get("org_id")
    org = await get_org(org_id)
    breakdown = await get_org_usage_breakdown(org_id, days=30)
    usage = await get_user_usage(user["id"])
    feedback_list = await get_all_feedback(limit=50)

    return templates.TemplateResponse(
        "usage_dashboard.html",
        {
            "request": request,
            "user": user,
            "org": org,
            "breakdown": breakdown,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": True,
            "feedback_list": feedback_list,
        }
    )
