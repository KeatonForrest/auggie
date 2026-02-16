"""
main.py - FastAPI Application Entry Point

Run: uvicorn main:app --reload
Open: http://localhost:8000
Docs: http://localhost:8000/docs/api
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

from config import get_settings as _get_settings

_boot_settings = _get_settings()
_is_production = "localhost" not in _boot_settings.app_url

# --- Request ID context var (available to logging filter) ---
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIDFilter(logging.Filter):
    """Inject request_id into every log record."""
    def filter(self, record):
        record.request_id = _request_id_ctx.get("-")
        return True


# --- Logging setup ---
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_root.addFilter(_RequestIDFilter())

if _is_production:
    from pythonjsonlogger import jsonlogger
    _handler = logging.StreamHandler()
    _handler.setFormatter(jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    ))
    _root.addHandler(_handler)
else:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        level=logging.INFO,
    )

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

import pydantic

from config import get_settings
from database import init_database, close_database, get_all_documents, get_user_usage, get_user_materials

# --- Request ID middleware ---
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        _request_id_ctx.set(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
from api.ratelimit import _rate_limit_info

from services.collect import close_shared_http_client
from auth import router as auth_router, get_current_user
from billing import router as billing_router
from api.routes import router as api_v1_router
from api.webhooks import router as webhooks_router
from routes.integrations import router as integrations_router
from routes.lists import router as lists_router
from routes.research import router as research_router
from routes.team import router as team_router
from routes.settings import router as settings_router
from routes.admin import router as admin_router
from routes.watchlist import router as watchlist_router
from routes.platforms import router as platforms_router
from routes._helpers import templates

settings = get_settings()

_is_https = settings.app_url.startswith("https")


class RateLimitHeaderMiddleware:
    """Pure ASGI middleware that sets X-RateLimit-* headers from ContextVar."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                info = _rate_limit_info.get(None)
                if info is not None:
                    headers = list(message.get("headers", []))
                    headers.append((b"x-ratelimit-limit", str(info.limit).encode()))
                    headers.append((b"x-ratelimit-remaining", str(info.remaining).encode()))
                    headers.append((b"x-ratelimit-reset", str(info.reset).encode()))
                    message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class LatencyLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start
        if duration > 1.0:
            logger.warning("SLOW %s %s -> %s (%.2fs)", request.method, request.url.path, response.status_code, duration)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https://*.googleusercontent.com data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        if _is_https:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup, close on shutdown."""
    logger.info("Initializing database...")
    await init_database()
    logger.info("Database ready!")
    # Warn if default session secret is used in non-localhost mode
    if "localhost" not in settings.app_url and settings.session_secret == "dev-secret-change-in-production":
        logger.warning("Using default session secret in production! Set SESSION_SECRET to a strong random value.")

    # Start the task queue worker in-process
    import asyncio as _asyncio
    _worker_task = None
    if settings.worker_enabled:
        from worker import _poll_loop, _shutdown, WORKER_ID
        _sem = _asyncio.Semaphore(settings.worker_concurrency)
        _worker_task = _asyncio.create_task(_poll_loop(_sem))
        logger.info("In-process worker %s started", WORKER_ID)

    yield

    # Shut down worker gracefully
    if _worker_task is not None:
        from worker import _shutdown
        logger.info("Shutting down worker...")
        _shutdown.set()
        # Wait for the poll loop to exit
        try:
            await _asyncio.wait_for(_worker_task, timeout=5)
        except (_asyncio.TimeoutError, _asyncio.CancelledError):
            _worker_task.cancel()
            try:
                await _worker_task
            except _asyncio.CancelledError:
                pass
        # Wait for in-flight dispatched tasks to drain
        logger.info("Waiting for in-flight tasks to complete...")
        try:
            for _ in range(settings.worker_concurrency):
                await _asyncio.wait_for(_sem.acquire(), timeout=30)
        except _asyncio.TimeoutError:
            logger.warning("In-flight tasks did not finish within 30s")

    logger.info("Shutting down...")
    await close_shared_http_client()
    await close_database()
    logger.info("Database connections closed.")


_openapi_tags = [
    {"name": "Account", "description": "Account info, credits, and API key usage"},
    {"name": "Research", "description": "Start and poll async research jobs"},
    {"name": "Sequences", "description": "Generate outreach email sequences"},
    {"name": "Bulk", "description": "Bulk research operations (up to 100 URLs)"},
    {"name": "Lists", "description": "Persistent scored account lists"},
    {"name": "Team", "description": "Organization member management"},
    {"name": "Webhooks", "description": "Webhook configuration and delivery"},
    {"name": "Watchlist", "description": "Recurring research on watched companies"},
]

app = FastAPI(
    title="Auggie",
    description="AI-powered account research for sales teams",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs/api",
    openapi_tags=_openapi_tags,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Request ID (outermost = first to run)
app.add_middleware(RequestIDMiddleware)

# Latency logging
app.add_middleware(LatencyLoggingMiddleware)

# Security headers
app.add_middleware(SecurityHeadersMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_url],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=True,
)

# Session middleware for OAuth state
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=_is_https,
    same_site="lax",
)

# Rate limit headers (pure ASGI — reads ContextVar set by endpoint rate limiters)
app.add_middleware(RateLimitHeaderMiddleware)

# Include routers
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(api_v1_router)
app.include_router(webhooks_router)
app.include_router(integrations_router)
app.include_router(lists_router)
app.include_router(research_router)
app.include_router(team_router)
app.include_router(settings_router)
app.include_router(admin_router)
app.include_router(watchlist_router)
app.include_router(platforms_router)


@app.get("/health")
async def health_check():
    """Unauthenticated health check for uptime monitors and Railway."""
    from database import _pool
    try:
        async with _pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return JSONResponse({"status": "ok", "db": "ok"})
    except Exception:
        return JSONResponse({"status": "degraded", "db": "error"}, status_code=503)

_ERROR_TITLES = {
    400: "Invalid Request",
    402: "Insufficient Credits",
    403: "Forbidden",
    404: "Not Found",
    500: "Something Went Wrong",
}

_STATUS_TO_CODE = {
    400: "validation_error",
    401: "unauthorized",
    402: "insufficient_credits",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limit_exceeded",
    500: "internal_error",
}

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        title = _ERROR_TITLES.get(exc.status_code, "Error")
        detail = exc.detail if isinstance(exc.detail, str) else (exc.detail or {}).get("message", "An unexpected error occurred.")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "status_code": exc.status_code, "title": title, "detail": detail},
            status_code=exc.status_code,
        )
    # Structured error format: {"error": {"code": ..., "message": ...}}
    request_id = getattr(request.state, "request_id", None)
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        error_body = {**exc.detail}
        if request_id:
            error_body["request_id"] = request_id
        resp = JSONResponse({"error": error_body}, status_code=exc.status_code)
        if exc.headers:
            for k, v in exc.headers.items():
                resp.headers[k] = v
        return resp
    # Legacy HTTPException with string detail
    code = _STATUS_TO_CODE.get(exc.status_code, "internal_error")
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    error_body = {"code": code, "message": message}
    if request_id:
        error_body["request_id"] = request_id
    return JSONResponse({"error": error_body}, status_code=exc.status_code)


@app.exception_handler(pydantic.ValidationError)
async def pydantic_validation_handler(request: Request, exc: pydantic.ValidationError):
    request_id = getattr(request.state, "request_id", None)
    error_body = {"code": "validation_error", "message": str(exc)}
    if request_id:
        error_body["request_id"] = request_id
    return JSONResponse({"error": error_body}, status_code=400)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "status_code": 500, "title": "Something Went Wrong", "detail": "Internal server error"},
            status_code=500,
        )
    request_id = getattr(request.state, "request_id", None)
    error_body = {"code": "internal_error", "message": "Internal server error"}
    if request_id:
        error_body["request_id"] = request_id
    return JSONResponse({"error": error_body}, status_code=500)


# =============================================================================
# Home page + static pages
# =============================================================================

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    """Privacy policy page."""
    return templates.TemplateResponse("privacy.html", {"request": request})


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    """Terms of service page."""
    return templates.TemplateResponse("terms.html", {"request": request})


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page - shows login or dashboard based on auth state."""
    user = await get_current_user(request)

    if not user:
        # Show landing/login page
        return templates.TemplateResponse(
            "landing.html",
            {"request": request}
        )

    if not user.get("product_context"):
        # Redirect to onboarding
        return RedirectResponse(url="/onboarding", status_code=302)

    # Show dashboard with user's documents
    recent_docs = await get_all_documents(user_id=user["id"], limit=10)
    usage = await get_user_usage(user["id"])

    # Check if user has materials (for prompt)
    show_materials_prompt = False
    if settings.materials_enabled:
        materials = await get_user_materials(user["id"])
        show_materials_prompt = len(materials) == 0

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user": user,
            "recent_docs": recent_docs,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "show_materials_prompt": show_materials_prompt,
            "materials_enabled": settings.materials_enabled,
        }
    )


@app.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    """Public API documentation page."""
    user = await get_current_user(request)
    return templates.TemplateResponse(
        "docs.html",
        {"request": request, "user": user}
    )


@app.get("/automations", response_class=HTMLResponse)
async def automations_redirect():
    """Redirect legacy automations URL to platforms hub."""
    return RedirectResponse(url="/platforms", status_code=301)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
