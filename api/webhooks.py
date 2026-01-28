"""Webhook CRUD endpoints + HMAC signing."""

import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl

from api.auth import require_api_key
from database import upsert_webhook, get_user_webhook, delete_user_webhook

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


class WebhookRegisterRequest(BaseModel):
    url: HttpUrl


class WebhookResponse(BaseModel):
    url: str
    secret: str
    active: bool


class WebhookInfo(BaseModel):
    url: str
    active: bool


def sign_payload(payload: dict, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest for a JSON payload."""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@router.post("/register", response_model=WebhookResponse)
async def register_webhook(body: WebhookRegisterRequest, api_user: dict = Depends(require_api_key)):
    """Register or update a webhook URL. Returns the secret for signature verification."""
    secret = secrets.token_hex(32)
    wh = await upsert_webhook(api_user["user_id"], str(body.url), secret)
    return WebhookResponse(url=wh["url"], secret=wh["secret"], active=wh["active"])


@router.get("", response_model=WebhookInfo | None)
async def get_webhook(api_user: dict = Depends(require_api_key)):
    """Get the current webhook configuration."""
    wh = await get_user_webhook(api_user["user_id"])
    if not wh:
        return None
    return WebhookInfo(url=wh["url"], active=wh["active"])


@router.delete("", status_code=204)
async def remove_webhook(api_user: dict = Depends(require_api_key)):
    """Remove (deactivate) the webhook."""
    deleted = await delete_user_webhook(api_user["user_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="No active webhook found")
