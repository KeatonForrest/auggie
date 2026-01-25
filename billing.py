"""billing.py - Stripe subscription management."""

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse

from config import get_settings
from database import update_user_stripe, reset_user_searches, get_user_by_id, add_bonus_credits
from auth import require_auth

router = APIRouter(prefix="/billing", tags=["billing"])

settings = get_settings()
stripe.api_key = settings.stripe_secret_key

# Price: $24.99/month for 25 searches (~1 account per workday)
PRICE_ID = None  # Will be set after creating the product

# Credit pack: $10 for 10 additional searches
CREDIT_PACK_PRICE_ID = None


async def get_or_create_price():
    """Get existing price or create product + price in Stripe."""
    global PRICE_ID
    if PRICE_ID:
        return PRICE_ID

    # Check if product already exists
    products = stripe.Product.list(limit=10)
    for product in products.data:
        if product.name == "Auggie Pro":
            # Get the price for this product
            prices = stripe.Price.list(product=product.id, active=True, limit=1)
            if prices.data:
                PRICE_ID = prices.data[0].id
                print(f"Found existing price: {PRICE_ID}")
                return PRICE_ID

    # Create new product and price
    product = stripe.Product.create(
        name="Auggie Pro",
        description="25 AI-powered account research documents per month",
    )

    price = stripe.Price.create(
        product=product.id,
        unit_amount=2499,  # $24.99 in cents
        currency="usd",
        recurring={"interval": "month"},
    )

    PRICE_ID = price.id
    print(f"Created new price: {PRICE_ID}")
    return PRICE_ID


async def get_or_create_credit_pack_price():
    """Get existing credit pack price or create product + price in Stripe."""
    global CREDIT_PACK_PRICE_ID
    if CREDIT_PACK_PRICE_ID:
        return CREDIT_PACK_PRICE_ID

    # Check if product already exists
    products = stripe.Product.list(limit=20)
    for product in products.data:
        if product.name == "Auggie Credit Pack":
            # Get the price for this product
            prices = stripe.Price.list(product=product.id, active=True, limit=1)
            if prices.data:
                CREDIT_PACK_PRICE_ID = prices.data[0].id
                print(f"Found existing credit pack price: {CREDIT_PACK_PRICE_ID}")
                return CREDIT_PACK_PRICE_ID

    # Create new product and price
    product = stripe.Product.create(
        name="Auggie Credit Pack",
        description="10 additional research credits",
    )

    price = stripe.Price.create(
        product=product.id,
        unit_amount=1000,  # $10 in cents
        currency="usd",
    )

    CREDIT_PACK_PRICE_ID = price.id
    print(f"Created new credit pack price: {CREDIT_PACK_PRICE_ID}")
    return CREDIT_PACK_PRICE_ID


@router.get("/subscribe")
async def create_checkout_session(request: Request, user: dict = Depends(require_auth)):
    """Create a Stripe checkout session and redirect to payment."""
    price_id = await get_or_create_price()

    # Create or get Stripe customer
    if user.get("stripe_customer_id"):
        customer_id = user["stripe_customer_id"]
    else:
        customer = stripe.Customer.create(
            email=user["email"],
            name=user.get("name", ""),
            metadata={"user_id": str(user["id"])},
        )
        customer_id = customer.id
        await update_user_stripe(user["id"], customer_id)

    # Create checkout session
    checkout_session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.app_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_url}/billing/cancel",
        metadata={"user_id": str(user["id"])},
    )

    return RedirectResponse(url=checkout_session.url, status_code=303)


@router.get("/success")
async def checkout_success(request: Request, session_id: str, user: dict = Depends(require_auth)):
    """Handle successful checkout."""
    # Retrieve the session to get subscription details
    session = stripe.checkout.Session.retrieve(session_id)

    if session.subscription:
        subscription = stripe.Subscription.retrieve(session.subscription)
        await update_user_stripe(
            user_id=user["id"],
            stripe_customer_id=session.customer,
            stripe_subscription_id=subscription.id,
            subscription_status="active",
        )
        # Reset search count for new subscription
        await reset_user_searches(user["id"])

    return RedirectResponse(url="/", status_code=302)


@router.get("/cancel")
async def checkout_cancel(request: Request):
    """Handle cancelled checkout."""
    return RedirectResponse(url="/", status_code=302)


@router.get("/buy-credits")
async def buy_credits(request: Request, user: dict = Depends(require_auth)):
    """Create a Stripe checkout session for credit pack purchase."""
    price_id = await get_or_create_credit_pack_price()

    # Create or get Stripe customer
    if user.get("stripe_customer_id"):
        customer_id = user["stripe_customer_id"]
    else:
        customer = stripe.Customer.create(
            email=user["email"],
            name=user.get("name", ""),
            metadata={"user_id": str(user["id"])},
        )
        customer_id = customer.id
        await update_user_stripe(user["id"], customer_id)

    # Create checkout session for one-time payment
    checkout_session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="payment",  # One-time payment, not subscription
        success_url=f"{settings.app_url}/billing/credits-success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.app_url}/billing/cancel",
        metadata={"user_id": str(user["id"]), "credits": "10"},
    )

    return RedirectResponse(url=checkout_session.url, status_code=303)


@router.get("/credits-success")
async def credits_success(request: Request, session_id: str, user: dict = Depends(require_auth)):
    """Handle successful credit pack purchase."""
    session = stripe.checkout.Session.retrieve(session_id)

    # Verify payment was successful
    if session.payment_status == "paid":
        credits = int(session.metadata.get("credits", 10))
        await add_bonus_credits(user["id"], credits)
        print(f"Added {credits} bonus credits to user {user['id']}")

    return RedirectResponse(url="/", status_code=302)


@router.get("/portal")
async def customer_portal(request: Request, user: dict = Depends(require_auth)):
    """Redirect to Stripe customer portal for managing subscription."""
    if not user.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="No subscription found")

    portal_session = stripe.billing_portal.Session.create(
        customer=user["stripe_customer_id"],
        return_url=f"{settings.app_url}/",
    )

    return RedirectResponse(url=portal_session.url, status_code=303)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    # Verify webhook signature (skip in dev if no secret set)
    if settings.stripe_webhook_secret and settings.stripe_webhook_secret != "whsec_placeholder":
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # Dev mode: parse without verification
        import json
        event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)

    # Handle subscription events
    if event.type == "customer.subscription.created":
        subscription = event.data.object
        await handle_subscription_change(subscription, "active")

    elif event.type == "customer.subscription.updated":
        subscription = event.data.object
        status = "active" if subscription.status == "active" else subscription.status
        await handle_subscription_change(subscription, status)

    elif event.type == "customer.subscription.deleted":
        subscription = event.data.object
        await handle_subscription_change(subscription, "canceled")

    elif event.type == "invoice.paid":
        invoice = event.data.object
        if invoice.subscription:
            # Reset search count on successful payment
            customer_id = invoice.customer
            # Find user by customer ID and reset searches
            await reset_searches_for_customer(customer_id)

    return {"status": "success"}


async def handle_subscription_change(subscription, status: str):
    """Update user's subscription status."""
    customer_id = subscription.customer
    subscription_id = subscription.id

    # Find user by Stripe customer ID
    from database import get_connection
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE stripe_customer_id = $1",
            customer_id
        )
        if row:
            await update_user_stripe(
                user_id=row["id"],
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                subscription_status=status,
            )
            print(f"Updated user {row['id']} subscription status to {status}")


async def reset_searches_for_customer(customer_id: str):
    """Reset search count for a customer after payment."""
    from database import get_connection
    async with get_connection() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE stripe_customer_id = $1",
            customer_id
        )
        if row:
            await reset_user_searches(row["id"])
            print(f"Reset searches for user {row['id']}")
