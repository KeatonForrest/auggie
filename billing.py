"""billing.py - Stripe credit purchases."""

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse

from config import get_settings
from database import update_user_stripe, get_user_by_id, fulfill_session, update_org_stripe
from auth import require_auth, require_org_admin

router = APIRouter(prefix="/billing", tags=["billing"])

settings = get_settings()
stripe.api_key = settings.stripe_secret_key

# Credit pack: $10 for 10 credits
CREDIT_PACK_PRICE_ID = None


async def get_or_create_credit_pack_price():
    """Get existing credit pack price or create product + price in Stripe."""
    global CREDIT_PACK_PRICE_ID
    if CREDIT_PACK_PRICE_ID:
        return CREDIT_PACK_PRICE_ID

    # Check if product already exists
    products = stripe.Product.list(limit=20)
    for product in products.data:
        if product.name == "Auggie Credits":
            # Get the price for this product
            prices = stripe.Price.list(product=product.id, active=True, limit=1)
            if prices.data:
                CREDIT_PACK_PRICE_ID = prices.data[0].id
                print(f"Found existing credit pack price: {CREDIT_PACK_PRICE_ID}")
                return CREDIT_PACK_PRICE_ID

    # Create new product and price
    product = stripe.Product.create(
        name="Auggie Credits",
        description="10 research credits",
    )

    price = stripe.Price.create(
        product=product.id,
        unit_amount=1000,  # $10 in cents
        currency="usd",
    )

    CREDIT_PACK_PRICE_ID = price.id
    print(f"Created new credit pack price: {CREDIT_PACK_PRICE_ID}")
    return CREDIT_PACK_PRICE_ID


@router.get("/buy-credits")
async def buy_credits(request: Request, user: dict = Depends(require_auth)):
    """Create a Stripe checkout session for credit purchase (admin only)."""
    if user.get("org_role") != "admin":
        raise HTTPException(status_code=403, detail="Only team admins can purchase credits. Ask your admin to buy credits or change your role.")
    price_id = await get_or_create_credit_pack_price()

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
        cancel_url=f"{settings.app_url}/",
        metadata={"user_id": str(user["id"]), "org_id": str(user.get("org_id", "")), "credits": "10"},
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
                print(f"[Webhook] Fulfilled {credits} credits for user {user_id} (session {session.id})")
            else:
                print(f"[Webhook] Session {session.id} already fulfilled, skipping")

    return {"status": "success"}
