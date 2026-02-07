"""billing.py - Stripe credit purchases."""

import logging
import stripe

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from config import get_settings
from database import update_user_stripe, get_user_by_id, fulfill_session, update_org_stripe
from auth import require_auth, require_org_admin

router = APIRouter(prefix="/billing", tags=["billing"])
templates = Jinja2Templates(directory="templates")

settings = get_settings()
stripe.api_key = settings.stripe_secret_key

# Credit tiers: {tier_name: (credits, price_in_cents)}
CREDIT_TIERS = {
    "starter": (10, 1000),      # $10 for 10 credits
    "growth": (100, 5000),      # $50 for 100 credits
    "power": (500, 10000),      # $100 for 500 credits
}

# Cache: tier_name -> Stripe price ID
_tier_price_ids: dict[str, str] = {}


async def get_or_create_tier_price(tier: str) -> str:
    """Get existing Stripe price for a tier or create product + price."""
    if tier in _tier_price_ids:
        return _tier_price_ids[tier]

    credits, price_cents = CREDIT_TIERS[tier]
    product_name = f"Auggie Credits — {credits} pack"

    # Check if product already exists
    products = stripe.Product.list(limit=50)
    for product in products.data:
        if product.name == product_name:
            prices = stripe.Price.list(product=product.id, active=True, limit=1)
            if prices.data:
                _tier_price_ids[tier] = prices.data[0].id
                logger.info("Found existing price for %s: %s", tier, _tier_price_ids[tier])
                return _tier_price_ids[tier]

    # Also check the legacy "Auggie Credits" product for backward compat (starter tier)
    if tier == "starter":
        for product in products.data:
            if product.name == "Auggie Credits":
                prices = stripe.Price.list(product=product.id, active=True, limit=1)
                if prices.data and prices.data[0].unit_amount == price_cents:
                    _tier_price_ids[tier] = prices.data[0].id
                    logger.info("Found legacy price for starter: %s", _tier_price_ids[tier])
                    return _tier_price_ids[tier]

    # Create new product and price
    product = stripe.Product.create(
        name=product_name,
        description=f"{credits} research credits",
    )

    price = stripe.Price.create(
        product=product.id,
        unit_amount=price_cents,
        currency="usd",
    )

    _tier_price_ids[tier] = price.id
    logger.info("Created new price for %s: %s", tier, _tier_price_ids[tier])
    return _tier_price_ids[tier]


@router.get("/buy-credits")
async def buy_credits(request: Request, tier: str | None = None, user: dict = Depends(require_auth)):
    """Show tier selection page, or redirect to Stripe checkout if tier is specified."""
    if user.get("org_role") != "admin":
        raise HTTPException(status_code=403, detail="Only team admins can purchase credits. Ask your admin to buy credits or change your role.")

    # No tier selected — show the selection page
    if not tier:
        from database import get_user_usage
        usage = await get_user_usage(user["id"])
        credits = usage.get("bonus_credits", 0) / 100
        return templates.TemplateResponse("buy_credits.html", {
            "request": request,
            "user": user,
            "credits": credits,
        })

    # Validate tier
    if tier not in CREDIT_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Choose from: {', '.join(CREDIT_TIERS.keys())}")

    credits, price_cents = CREDIT_TIERS[tier]
    price_id = await get_or_create_tier_price(tier)

    # Create or get Stripe customer on the org
    org_customer_id = user.get("org_stripe_customer_id")
    if org_customer_id:
        customer_id = org_customer_id
    else:
        customer = stripe.Customer.create(
            email=user["email"],
            name=user.get("org_name") or user.get("name", ""),
            metadata={"user_id": str(user["id"]), "org_id": str(user.get("org_id", ""))},
        )
        customer_id = customer.id
        if user.get("org_id"):
            await update_org_stripe(user["org_id"], customer_id)
        await update_user_stripe(user["id"], customer_id)

    # Create checkout session for one-time payment
    checkout_session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="payment",
        success_url=f"{settings.app_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_url}/billing/buy-credits",
        metadata={"user_id": str(user["id"]), "org_id": str(user.get("org_id", "")), "credits": str(credits)},
    )

    return RedirectResponse(url=checkout_session.url, status_code=303)


@router.get("/success")
async def credits_success(request: Request, session_id: str, user: dict = Depends(require_auth)):
    """Handle successful credit purchase."""
    # Just redirect — credits are fulfilled only via the webhook
    return RedirectResponse(url="/?payment=success", status_code=302)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events for credit purchases."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    # Verify webhook signature
    has_valid_secret = settings.stripe_webhook_secret and settings.stripe_webhook_secret != "whsec_placeholder"
    is_local_dev = "localhost" in settings.app_url

    if has_valid_secret:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    elif is_local_dev:
        # Dev mode: parse without verification
        import json
        event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    else:
        # Production without valid webhook secret — reject
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    # Handle checkout completion (idempotent via fulfill_session)
    if event.type == "checkout.session.completed":
        session = event.data.object
        if session.mode == "payment" and session.payment_status == "paid":
            credits = int(session.metadata.get("credits", 10))
            user_id = int(session.metadata.get("user_id"))
            added = await fulfill_session(session.id, user_id, credits)
            if added:
                logger.info("[Webhook] Fulfilled %d credits for user %d (session %s)", credits, user_id, session.id)
            else:
                logger.info("[Webhook] Session %s already fulfilled, skipping", session.id)

    return {"status": "success"}
