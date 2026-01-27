# Microsoft OAuth Implementation Guide

## Overview
Add Microsoft sign-in alongside existing Google OAuth to support MSP customers who use Azure/M365.

---

## 1. Azure Portal Setup

### Register the Application
1. Go to [Azure Portal](https://portal.azure.com) → Azure Active Directory → App registrations
2. Click "New registration"
3. Configure:
   - **Name:** Auggie
   - **Supported account types:** "Accounts in any organizational directory (Any Azure AD directory - Multitenant) and personal Microsoft accounts"
   - **Redirect URI:** Web → `https://auggie.tools/auth/microsoft/callback`
4. Click "Register"

### Get Credentials
1. Copy **Application (client) ID** → This is your `MICROSOFT_CLIENT_ID`
2. Go to "Certificates & secrets" → "New client secret"
3. Add description, set expiration, click "Add"
4. Copy the **Value** immediately → This is your `MICROSOFT_CLIENT_SECRET`

### Configure API Permissions
Default permissions (User.Read) are sufficient for basic profile info.

---

## 2. Environment Variables

Add to `.env`:
```bash
MICROSOFT_CLIENT_ID=your_application_client_id
MICROSOFT_CLIENT_SECRET=your_client_secret_value
```

---

## 3. Code Changes

### 3.1 config.py

```python
# Add to Settings class after Google OAuth fields:

    # Microsoft OAuth (for MSP customers)
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
```

### 3.2 database.py

Add `microsoft_id` column to users table:

```python
# In init_database(), update the CREATE TABLE users statement:

await conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,

        -- Auth
        email TEXT UNIQUE NOT NULL,
        name TEXT,
        picture TEXT,
        google_id TEXT UNIQUE,          -- Changed: removed NOT NULL
        microsoft_id TEXT UNIQUE,       -- Added: Microsoft auth

        -- ... rest of fields unchanged
    )
""")

# Add migration for existing databases:
try:
    await conn.execute("ALTER TABLE users ADD COLUMN microsoft_id TEXT UNIQUE")
except asyncpg.exceptions.DuplicateColumnError:
    pass

# Make google_id nullable for existing databases:
try:
    await conn.execute("ALTER TABLE users ALTER COLUMN google_id DROP NOT NULL")
except Exception:
    pass  # Already nullable or doesn't exist
```

Add new database functions:

```python
async def get_user_by_microsoft_id(microsoft_id: str) -> Optional[dict]:
    """Get a user by their Microsoft ID."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE microsoft_id = $1",
            microsoft_id
        )
        return dict(row) if row else None


async def create_user_microsoft(email: str, name: str, picture: str, microsoft_id: str) -> dict:
    """Create a new user from Microsoft OAuth data."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, name, picture, microsoft_id)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            email, name, picture, microsoft_id
        )
        return dict(row)


async def link_microsoft_to_user(user_id: int, microsoft_id: str) -> dict:
    """Link a Microsoft account to an existing user (for account linking)."""
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users SET microsoft_id = $2 WHERE id = $1
            RETURNING *
            """,
            user_id, microsoft_id
        )
        return dict(row)
```

Update imports in auth.py:
```python
from database import (
    get_user_by_google_id, get_user_by_microsoft_id,
    create_user, create_user_microsoft, get_user_by_id
)
```

### 3.3 auth.py

Add Microsoft OAuth provider:

```python
# After the Google OAuth registration, add:

# Microsoft OAuth (optional - only register if configured)
if settings.microsoft_client_id:
    oauth.register(
        name="microsoft",
        client_id=settings.microsoft_client_id,
        client_secret=settings.microsoft_client_secret,
        server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
```

Add Microsoft auth routes:

```python
@router.get("/microsoft")
async def login_microsoft(request: Request):
    """Redirect to Microsoft OAuth."""
    if not settings.microsoft_client_id:
        raise HTTPException(status_code=404, detail="Microsoft auth not configured")
    redirect_uri = f"{settings.app_url}/auth/microsoft/callback"
    return await oauth.microsoft.authorize_redirect(request, redirect_uri)


@router.get("/microsoft/callback")
async def microsoft_callback(request: Request):
    """Handle Microsoft OAuth callback."""
    if not settings.microsoft_client_id:
        raise HTTPException(status_code=404, detail="Microsoft auth not configured")

    try:
        token = await oauth.microsoft.authorize_access_token(request)
    except Exception as e:
        print(f"Microsoft OAuth error: {e}")
        raise HTTPException(status_code=400, detail="Microsoft authentication failed")

    # Microsoft returns user info differently - need to decode the id_token
    # or call the userinfo endpoint
    user_info = token.get("userinfo")
    if not user_info:
        # Fallback: decode id_token
        import jwt
        id_token = token.get("id_token")
        if id_token:
            # Don't verify since we just got it from Microsoft
            user_info = jwt.decode(id_token, options={"verify_signature": False})

    if not user_info:
        raise HTTPException(status_code=400, detail="Failed to get user info from Microsoft")

    # Microsoft uses 'oid' (object ID) or 'sub' as unique identifier
    microsoft_id = user_info.get("oid") or user_info.get("sub")
    email = user_info.get("email") or user_info.get("preferred_username")
    name = user_info.get("name", "")
    picture = ""  # Microsoft doesn't provide picture in basic scope

    if not email:
        raise HTTPException(status_code=400, detail="Email not provided by Microsoft")

    # Get or create user
    user = await get_user_by_microsoft_id(microsoft_id)
    if not user:
        # Check if user exists with this email (maybe they signed up with Google)
        # For now, create new user. Account linking can be added later.
        user = await create_user_microsoft(
            email=email,
            name=name,
            picture=picture,
            microsoft_id=microsoft_id,
        )
        print(f"Created new user (Microsoft): {email}")
    else:
        print(f"Existing user logged in (Microsoft): {email}")

    # Store user_id in session
    request.session["user_id"] = user["id"]
    print(f"Stored user_id {user['id']} in session")

    # Redirect based on onboarding status
    if user.get("product_context"):
        redirect_url = "/"
    else:
        redirect_url = "/onboarding"

    return RedirectResponse(url=redirect_url, status_code=302)
```

### 3.4 templates/landing.html

Update the login buttons to show both options:

```html
<!-- Replace the single Google button in the nav with: -->
<div class="flex items-center gap-2">
    <a href="/auth/login" class="flex items-center gap-2 bg-white border border-gray-300 text-gray-700 px-3 py-2 rounded-lg text-sm hover:bg-gray-50">
        <svg class="w-4 h-4" viewBox="0 0 24 24">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
        </svg>
        Google
    </a>
    <a href="/auth/microsoft" class="flex items-center gap-2 bg-white border border-gray-300 text-gray-700 px-3 py-2 rounded-lg text-sm hover:bg-gray-50">
        <svg class="w-4 h-4" viewBox="0 0 23 23">
            <path fill="#f35325" d="M1 1h10v10H1z"/>
            <path fill="#81bc06" d="M12 1h10v10H12z"/>
            <path fill="#05a6f0" d="M1 12h10v10H1z"/>
            <path fill="#ffba08" d="M12 12h10v10H12z"/>
        </svg>
        Microsoft
    </a>
</div>

<!-- Replace the main CTA button with: -->
<div class="flex flex-col sm:flex-row items-center justify-center gap-4">
    <a href="/auth/login" class="inline-flex items-center gap-2 bg-white border-2 border-gray-200 text-gray-700 px-6 py-3 rounded-lg text-lg font-medium hover:bg-gray-50 transition shadow-sm">
        <svg class="w-5 h-5" viewBox="0 0 24 24">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
        </svg>
        Sign in with Google
    </a>
    <a href="/auth/microsoft" class="inline-flex items-center gap-2 bg-[#0078d4] text-white px-6 py-3 rounded-lg text-lg font-medium hover:bg-[#106ebe] transition shadow-sm">
        <svg class="w-5 h-5" viewBox="0 0 23 23">
            <path fill="#fff" d="M1 1h10v10H1z" opacity="0.8"/>
            <path fill="#fff" d="M12 1h10v10H12z" opacity="0.9"/>
            <path fill="#fff" d="M1 12h10v10H1z" opacity="0.9"/>
            <path fill="#fff" d="M12 12h10v10H12z"/>
        </svg>
        Sign in with Microsoft
    </a>
</div>
<p class="mt-4 text-sm text-gray-500">Free to start. $24.99/month for 25 researches.</p>
```

---

## 4. Testing Checklist

- [ ] Register app in Azure Portal
- [ ] Add env vars to local .env
- [ ] Run migrations (start server to auto-migrate)
- [ ] Test Microsoft login with personal account
- [ ] Test Microsoft login with work/school account
- [ ] Verify user created in database with microsoft_id
- [ ] Verify session persists after login
- [ ] Test logout works
- [ ] Add env vars to Railway production
- [ ] Update Azure Portal redirect URI for production

---

## 5. Future Enhancements

### Account Linking
Allow users to link both Google and Microsoft to same account:
- If user logs in with Microsoft but email matches existing Google user, prompt to link
- Store both google_id and microsoft_id on same user record

### Profile Pictures
Microsoft Graph API can provide profile photos, but requires additional permissions:
- Add `User.Read` permission (already included)
- Call `https://graph.microsoft.com/v1.0/me/photo/$value` for photo

### Tenant Restrictions (Enterprise)
For enterprise SSO, restrict to specific Azure AD tenants:
- Change `common` to specific tenant ID in metadata URL
- Or use `organizations` to allow only work/school accounts

---

## 6. Rollback Plan

If issues arise:
1. Remove `microsoft_client_id` and `microsoft_client_secret` from env
2. The Microsoft OAuth routes will return 404
3. Existing Google users unaffected
4. Microsoft users can't log in until fixed (consider adding email-based fallback)
