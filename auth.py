"""auth.py - Google OAuth authentication."""

import jwt
from datetime import datetime, timedelta
from typing import Optional
from functools import wraps

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, HTMLResponse
from authlib.integrations.starlette_client import OAuth

from config import get_settings
from database import get_user_by_google_id, create_user, get_user_by_id

router = APIRouter(prefix="/auth", tags=["auth"])

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

# JWT settings
JWT_SECRET = settings.session_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 7


def create_access_token(user_id: int) -> str:
    """Create a JWT token for the user."""
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRATION_DAYS),
        "iat": datetime.utcnow(),
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
        print(f"Session user_id: {user_id}")

        if not user_id:
            # Fallback to cookie
            token = request.cookies.get("session")
            if token:
                user_id = decode_access_token(token)
                print(f"Cookie user_id: {user_id}")

        if not user_id:
            print("No user_id found in session or cookie")
            return None

        user = await get_user_by_id(user_id)
        print(f"Found user: {user.get('email') if user else None}")
        return user
    except Exception as e:
        print(f"Error getting current user: {e}")
        return None


async def require_auth(request: Request) -> dict:
    """Dependency that requires authentication."""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def require_onboarding(request: Request) -> dict:
    """Dependency that requires auth + completed onboarding."""
    user = await require_auth(request)
    if not user.get("product_context"):
        raise HTTPException(status_code=403, detail="Onboarding not completed")
    return user


@router.get("/login")
async def login(request: Request):
    """Redirect to Google OAuth."""
    redirect_uri = f"{settings.app_url}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    """Handle Google OAuth callback."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        print(f"OAuth error: {e}")
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
        print(f"Created new user: {email}")
    else:
        print(f"Existing user logged in: {email}")
    
    # Store user_id in session (managed by SessionMiddleware)
    request.session["user_id"] = user["id"]
    print(f"Stored user_id {user['id']} in session")

    # Redirect based on onboarding status
    if user.get("product_context"):
        redirect_url = "/"
    else:
        redirect_url = "/onboarding"

    print(f"Redirecting to {redirect_url}")
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
