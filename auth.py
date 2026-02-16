"""auth.py - Google OAuth authentication."""

import logging
import re
import jwt

logger = logging.getLogger(__name__)
from datetime import datetime, timedelta, timezone
from typing import Optional
from auth_cache import get_cached_user, set_cached_user, invalidate_user_cache

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth

from config import get_settings
from database import (
    get_user_by_google_id,
    get_user_by_microsoft_id,
    create_user,
    create_user_microsoft,
    get_user_by_id,
    get_pending_invites_for_email,
    accept_invite,
    get_user_usage,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Strict pattern for ?next= redirect URLs: only safe internal paths
_SAFE_NEXT_RE = re.compile(r"^/[a-zA-Z0-9][a-zA-Z0-9/_\-\.]*$")


def _is_safe_next_url(url: str) -> bool:
    """Validate that a next_url is a safe internal path (no open redirect)."""
    return bool(_SAFE_NEXT_RE.match(url))

# OAuth setup
oauth = OAuth()
settings = get_settings()

oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# Microsoft OAuth (optional - for MSP customers using Azure/M365)
# Note: We configure endpoints manually to avoid ID token issuer validation issues
# with the multi-tenant /common/ endpoint
if settings.microsoft_client_id:
    oauth.register(
        name="microsoft",
        client_id=settings.microsoft_client_id,
        client_secret=settings.microsoft_client_secret,
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        access_token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        jwks_uri="https://login.microsoftonline.com/common/discovery/v2.0/keys",
        userinfo_endpoint="https://graph.microsoft.com/oidc/userinfo",
        client_kwargs={
            "scope": "openid email profile",
            "token_endpoint_auth_method": "client_secret_post",
        },
    )

# JWT settings
JWT_SECRET = settings.jwt_secret or settings.session_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 7


def create_access_token(user_id: int) -> str:
    """Create a JWT token for the user."""
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRATION_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[int]:
    """Decode a JWT token and return the user_id, or None if invalid."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        return None


async def get_current_user(request: Request) -> Optional[dict]:
    """Get the current user from the session."""
    try:
        # Try session first (set by SessionMiddleware)
        user_id = request.session.get("user_id")
        logger.debug("Session lookup: found=%s", user_id is not None)

        if not user_id:
            # Fallback to cookie
            token = request.cookies.get("session")
            if token:
                user_id = decode_access_token(token)
                logger.debug("Cookie lookup: found=%s", user_id is not None)

        if not user_id:
            logger.debug("No user_id found in session or cookie")
            return None

        # Check cache first
        cached = get_cached_user(user_id)
        if cached is not None:
            return cached

        user = await get_user_by_id(user_id)
        logger.debug("User DB lookup: found=%s", user is not None)
        if user:
            set_cached_user(user_id, user)
        return user
    except Exception as e:
        logger.error("Error getting current user (%s): %s", type(e).__name__, e, extra={"event_type": "auth_session_error"})
        return None


async def require_auth(request: Request) -> dict:
    """Dependency that requires authentication."""
    user = await get_current_user(request)
    if not user:
        logger.warning("Authentication required but no valid session found", extra={"event_type": "auth_failure", "status_code": 401})
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def require_onboarding(request: Request) -> dict:
    """Dependency that requires auth + completed onboarding."""
    user = await require_auth(request)
    if not user.get("product_context"):
        raise HTTPException(status_code=403, detail="Onboarding not completed")
    return user


async def require_super_admin(request: Request) -> dict:
    """Dependency that requires auth + platform super admin."""
    user = await require_auth(request)
    usage = await get_user_usage(user["id"])
    if not usage or not usage.get("is_admin", False):
        raise HTTPException(status_code=404, detail="Not found")
    return user


async def require_org_admin(request: Request) -> dict:
    """Dependency that requires auth + org admin role."""
    user = await require_auth(request)
    if user.get("org_role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def _auto_accept_invites(user: dict) -> None:
    """Auto-accept any pending invites matching the user's email."""
    try:
        invites = await get_pending_invites_for_email(user["email"])
        if invites:
            # Accept the most recent invite
            await accept_invite(invites[0]["token"], user["id"])
            logger.info("Auto-accepted invite for %s to org %s", user["email"], invites[0].get("org_name"))
    except Exception as e:
        logger.error("Error auto-accepting invites: %s", e)


@router.get("/login")
async def login(request: Request):
    """Redirect to Google OAuth."""
    from api.ratelimit import auth_limiter, get_client_ip
    auth_limiter.check(get_client_ip(request))
    # Preserve ?next= param so we can redirect back after auth
    next_url = request.query_params.get("next")
    if next_url and _is_safe_next_url(next_url):
        request.session["next_url"] = next_url
    redirect_uri = f"{settings.app_url}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    """Handle Google OAuth callback."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        logger.error("OAuth error: %s", e, extra={"event_type": "oauth_callback_failure", "provider": "google", "status_code": 400})
        raise HTTPException(status_code=400, detail="OAuth authentication failed")
    
    user_info = token.get("userinfo")
    if not user_info:
        raise HTTPException(status_code=400, detail="Failed to get user info")
    
    google_id = user_info["sub"]
    email = user_info["email"]
    name = user_info.get("name", "")
    picture = user_info.get("picture", "")
    
    # Get or create user
    user = await get_user_by_google_id(google_id)
    if not user:
        user = await create_user(
            email=email,
            name=name,
            picture=picture,
            google_id=google_id,
        )
        logger.info("Created new user: %s", email)
    else:
        logger.info("Existing user logged in: %s", email)

    # Auto-accept pending org invites
    await _auto_accept_invites(user)

    # Store user_id in session (managed by SessionMiddleware)
    request.session["user_id"] = user["id"]
    logger.debug("Stored user_id in session")

    # Redirect to stored next_url, or based on onboarding status
    next_url = request.session.pop("next_url", None)
    if not user.get("product_context"):
        redirect_url = "/onboarding"
    elif next_url and _is_safe_next_url(next_url):
        redirect_url = next_url
    else:
        redirect_url = "/"

    logger.debug("Redirecting to %s", redirect_url)
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/microsoft")
async def login_microsoft(request: Request):
    """Redirect to Microsoft OAuth - manual implementation."""
    import secrets
    from api.ratelimit import auth_limiter, get_client_ip
    auth_limiter.check(get_client_ip(request))

    if not settings.microsoft_client_id:
        raise HTTPException(status_code=404, detail="Microsoft sign-in not available")

    # Preserve ?next= param so we can redirect back after auth
    next_url = request.query_params.get("next")
    if next_url and _is_safe_next_url(next_url):
        request.session["next_url"] = next_url

    # Generate and store state for CSRF protection
    state = secrets.token_urlsafe(24)
    request.session["_microsoft_authlib_state_"] = state

    redirect_uri = f"{settings.app_url}/auth/microsoft/callback"
    auth_url = (
        f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        f"?client_id={settings.microsoft_client_id}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&scope=openid%20email%20profile"
        f"&state={state}"
        f"&response_mode=query"
    )

    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/microsoft/callback")
async def microsoft_callback(request: Request):
    """Handle Microsoft OAuth callback - manual implementation to avoid authlib issuer validation."""
    import httpx

    if not settings.microsoft_client_id:
        raise HTTPException(status_code=404, detail="Microsoft sign-in not available")

    # Get the authorization code and state from the callback
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code:
        raise HTTPException(status_code=400, detail="No authorization code received")

    # Verify state matches session (CSRF protection)
    session_state = request.session.get("_microsoft_authlib_state_")
    if state != session_state:
        logger.error("Microsoft OAuth state mismatch", extra={"event_type": "oauth_callback_failure", "provider": "microsoft", "status_code": 400})
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    # Exchange code for tokens
    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    redirect_uri = f"{settings.app_url}/auth/microsoft/callback"

    async with httpx.AsyncClient() as client:
        # Get access token
        token_response = await client.post(
            token_url,
            data={
                "client_id": settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": "openid email profile",
            },
        )

        if token_response.status_code != 200:
            logger.error("Microsoft token exchange failed: %s", token_response.status_code, extra={"event_type": "oauth_callback_failure", "provider": "microsoft", "status_code": 400})
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")

        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            raise HTTPException(status_code=400, detail="No access token received")

        # Get user info from Microsoft Graph
        userinfo_response = await client.get(
            "https://graph.microsoft.com/oidc/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if userinfo_response.status_code != 200:
            logger.error("Microsoft userinfo fetch failed: %s", userinfo_response.status_code, extra={"event_type": "oauth_callback_failure", "provider": "microsoft", "status_code": 502})
            raise HTTPException(status_code=502, detail="Failed to get user info from Microsoft")
        else:
            user_info = userinfo_response.json()

    logger.debug("Microsoft OAuth callback completed")

    # Microsoft uses 'sub' as unique identifier in userinfo, 'oid' in id_token
    microsoft_id = user_info.get("sub") or user_info.get("oid")
    email = user_info.get("email") or user_info.get("preferred_username")
    name = user_info.get("name", "")
    picture = user_info.get("picture", "")

    if not microsoft_id:
        raise HTTPException(status_code=400, detail="Microsoft ID not provided")
    if not email:
        raise HTTPException(status_code=400, detail="Email not provided by Microsoft")

    # Get or create user
    user = await get_user_by_microsoft_id(microsoft_id)
    if not user:
        user = await create_user_microsoft(
            email=email,
            name=name,
            picture=picture,
            microsoft_id=microsoft_id,
        )
        logger.info("Created new user (Microsoft): %s", email)
    else:
        logger.info("Existing user logged in (Microsoft): %s", email)

    # Auto-accept pending org invites
    await _auto_accept_invites(user)

    # Store user_id in session
    request.session["user_id"] = user["id"]
    logger.debug("Stored user_id in session")

    # Redirect to stored next_url, or based on onboarding status
    next_url = request.session.pop("next_url", None)
    if not user.get("product_context"):
        redirect_url = "/onboarding"
    elif next_url and _is_safe_next_url(next_url):
        redirect_url = next_url
    else:
        redirect_url = "/"

    logger.debug("Redirecting to %s", redirect_url)
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Log out the user."""
    request.session.clear()
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session")
    return response


@router.get("/me")
async def get_me(user: dict = Depends(require_auth)):
    """Get current user info."""
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "picture": user["picture"],
        "company_name": user.get("company_name"),
        "product_context": user.get("product_context"),
        "industry": user.get("industry"),
        "subscription_status": user.get("subscription_status"),
        "searches_used": user.get("searches_used"),
    }
