"""Webhook CRUD endpoints + HMAC signing."""

import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, HttpUrl

from api.auth import require_api_key
from api.errors import APIError, _error_responses
from database import upsert_webhook, get_user_webhook, delete_user_webhook

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])


class WebhookRegisterRequest(BaseModel):
    url: HttpUrl = Field(..., description="HTTPS URL to receive webhook events", examples=["https://hooks.example.com/auggie"])


class WebhookResponse(BaseModel):
    url: str = Field(..., description="Registered webhook URL", examples=["https://hooks.example.com/auggie"])
    secret: str = Field(..., description="HMAC-SHA256 signing secret (store securely)", examples=["whsec_a1b2c3d4e5f6..."])
    active: bool = Field(..., description="Whether the webhook is active", examples=[True])


class WebhookInfo(BaseModel):
    url: str = Field(..., description="Registered webhook URL", examples=["https://hooks.example.com/auggie"])
    active: bool = Field(..., description="Whether the webhook is active", examples=[True])


def sign_payload(payload: dict, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest for a JSON payload."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@router.post("/register", response_model=WebhookResponse, responses={**_error_responses(401)})
async def register_webhook(body: WebhookRegisterRequest, api_user: dict = Depends(require_api_key)):
    """Register or update a webhook URL. Returns the secret for signature verification."""
    secret = secrets.token_hex(32)
    wh = await upsert_webhook(api_user["user_id"], str(body.url), secret, org_id=api_user.get("org_id"))
    return WebhookResponse(url=wh["url"], secret=wh["secret"], active=wh["active"])


@router.get("", response_model=WebhookInfo | None, responses={**_error_responses(401)})
async def get_webhook(api_user: dict = Depends(require_api_key)):
    """Get the current webhook configuration."""
    wh = await get_user_webhook(api_user["user_id"])
    if not wh:
        return None
    return WebhookInfo(url=wh["url"], active=wh["active"])


@router.delete("", status_code=204, responses={**_error_responses(401)})
async def remove_webhook(api_user: dict = Depends(require_api_key)):
    """Remove (deactivate) the webhook."""
    deleted = await delete_user_webhook(api_user["user_id"])
    if not deleted:
        raise APIError("not_found", "No active webhook found", 404)
