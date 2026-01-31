"""Shared utilities used across route modules."""

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from api.validation import validate_company_url
from api.tasks import create_tracked_task
from config import get_settings
from database import (
    get_user_usage, use_credit, refund_credit,
    get_enriched_contacts,
    create_list, add_list_accounts, update_list_credits,
    create_research_job, get_list_accounts,
    upsert_integration, delete_integration,
)
from services.materials import MaterialsService

logger = logging.getLogger(__name__)
settings = get_settings()
templates = Jinja2Templates(directory="templates")

# Lazy-initialized materials service
materials_service = None


def get_materials_service():
    """Get or create materials service (lazy init)."""
    global materials_service
    if materials_service is None and settings.materials_enabled:
        materials_service = MaterialsService()
    return materials_service


def normalize_url(url: str) -> str:
    """Add https:// if no protocol specified. For non-research URLs."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def parse_personas_string(personas_str: str) -> tuple[list[str], list[str]]:
    """Parse stored personas string back into levels and functions lists."""
    levels = []
    functions = []
    if not personas_str:
        return levels, functions

    # Format: "Levels: VP, Director | Functions: Sales / Revenue, Marketing"
    parts = personas_str.split(" | ")
    for part in parts:
        if part.startswith("Levels: "):
            levels = [l.strip() for l in part[8:].split(", ")]
        elif part.startswith("Functions: "):
            functions = [f.strip() for f in part[11:].split(", ")]

    return levels, functions


def _build_target_titles(user: dict) -> list[str]:
    """Build a list of target job titles from user's ICP settings."""
    levels, functions = parse_personas_string(user.get("target_personas") or "")

    title_map = {
        "C-Suite": {"Sales / Revenue": "CRO", "Marketing": "CMO", "Engineering / Product": "CTO",
                     "Finance / Accounting": "CFO", "Operations": "COO", "IT / Security": "CISO",
                     "HR / People": "CHRO", "Customer Success": "CCO", "Data Science / BI": "Chief Data Officer",
                     "Legal": "General Counsel"},
        "VP": {"Sales / Revenue": "VP Sales", "Marketing": "VP Marketing", "Engineering / Product": "VP Engineering",
               "Finance / Accounting": "VP Finance", "Operations": "VP Operations", "IT / Security": "VP IT",
               "HR / People": "VP People", "Customer Success": "VP Customer Success",
               "Data Science / BI": "VP Data", "Legal": "VP Legal"},
        "Director": {"Sales / Revenue": "Director of Sales", "Marketing": "Director of Marketing",
                     "Engineering / Product": "Director of Engineering", "Finance / Accounting": "Director of Finance",
                     "Operations": "Director of Operations", "IT / Security": "Director of IT",
                     "HR / People": "Director of HR", "Customer Success": "Director of Customer Success",
                     "Data Science / BI": "Director of Analytics"},
    }

    titles = []
    for level in levels:
        if level in title_map:
            for func in functions:
                if func in title_map[level]:
                    titles.append(title_map[level][func])

    if not titles:
        titles = ["CTO", "VP Engineering", "VP Sales", "CEO"]

    return titles[:5]


# ---------------------------------------------------------------------------
# Generic OAuth connect / callback / API-key helpers
# ---------------------------------------------------------------------------

async def _oauth_connect(request: Request, provider: str, get_authorize_url_fn):
    """Generic OAuth redirect: generate state, store in session, redirect."""
    state = secrets.token_urlsafe(24)
    request.session[f"_{provider}_state_"] = state
    url = get_authorize_url_fn(state)
    return RedirectResponse(url=url)


async def _oauth_callback(
    request: Request,
    user: dict,
    provider: str,
    exchange_code_fn,
    expires_in_default: int = 7200,
    metadata_fn=None,
):
    """Generic OAuth callback: verify state, exchange code, upsert integration."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or state != request.session.get(f"_{provider}_state_"):
        raise HTTPException(status_code=400, detail="Invalid OAuth callback")

    request.session.pop(f"_{provider}_state_", None)

    token_data = await exchange_code_fn(code)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=token_data.get("expires_in", expires_in_default)
    )

    kwargs = dict(
        user_id=user["id"],
        provider=provider,
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        token_expires_at=expires_at,
    )
    if metadata_fn:
        kwargs["metadata"] = metadata_fn(token_data)

    await upsert_integration(**kwargs)
    return RedirectResponse(url="/integrations", status_code=302)


async def _apikey_connect(user: dict, provider: str, api_key: str, validate_fn, error_label: str):
    """Generic API-key validation + save."""
    api_key = api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    valid = await validate_fn(api_key)
    if not valid:
        raise HTTPException(status_code=400, detail=f"Invalid {error_label}")

    await upsert_integration(user_id=user["id"], provider=provider, access_token=api_key)
    return JSONResponse({"success": True})


# ---------------------------------------------------------------------------
# Generic CRM import helper
# ---------------------------------------------------------------------------

async def _run_crm_import(
    user: dict,
    items: list,
    list_name: str,
    domain_extractor_fn,
    source_metadata_fn=None,
):
    """Generic CRM import: validate domains, check credits, create list, start analysis.

    domain_extractor_fn(item) -> (domain: str, extra_id: str | None)
    source_metadata_fn(id_map) -> dict | None — called with the populated URL→ID map
    """
    from api.jobs import run_list_analysis
    from database import set_list_source

    if not items:
        raise HTTPException(status_code=400, detail="No items selected")

    valid_urls = []
    id_map: dict[str, str] = {}
    seen: set[str] = set()
    for item in items:
        domain, extra_id = domain_extractor_fn(item)
        if not domain or domain in seen:
            continue
        url = normalize_url(domain)
        try:
            url = validate_company_url(url)
        except ValueError:
            continue
        seen.add(domain)
        valid_urls.append(url)
        if extra_id is not None:
            id_map[url] = extra_id
        if len(valid_urls) >= 100:
            break

    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid domains found")

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(valid_urls) * 100
    if not is_admin and usage.get("bonus_credits", 0) < needed:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. Need {len(valid_urls)}, have {usage.get('bonus_credits', 0) // 100}.",
        )

    if not is_admin:
        ok = await use_credit(user["id"], cents=needed)
        if not ok:
            return JSONResponse({"success": False, "error": "Not enough credits"}, status_code=402)

    lst = await create_list(user["id"], api_key_id=None, name=list_name)
    await add_list_accounts(lst["id"], valid_urls)
    await update_list_credits(lst["id"], needed)

    if source_metadata_fn:
        metadata = source_metadata_fn(id_map)
        if metadata:
            await set_list_source(lst["id"], metadata)

    await create_tracked_task(
        "list_analysis",
        {"list_id": lst["id"], "user_id": user["id"], "api_key_id": None, "is_admin": is_admin},
        name=f"list-{lst['id']}",
    )

    return JSONResponse({"success": True, "list_id": lst["id"]})


# ---------------------------------------------------------------------------
# Push-to-integration helpers
# ---------------------------------------------------------------------------

async def _push_contacts_to_integration(user: dict, list_id: int, campaign_id: str, account_ids: list[int], push_fn):
    """Push contacts to a campaign-based integration (Instantly, Smartlead)."""
    from database import get_list

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    if account_ids:
        accounts = await get_list_accounts(list_id, account_ids=account_ids, limit=10000)
    else:
        accounts = await get_list_accounts(list_id, status="completed", limit=10000)

    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts to push")

    contacts_by_account = {}
    for account in accounts:
        if account.get("document_id"):
            contacts = await get_enriched_contacts(account["document_id"], user["id"])
            if contacts:
                contacts_by_account[account["id"]] = contacts

    result = await push_fn(user["id"], campaign_id, accounts, contacts_by_account)
    return JSONResponse(result)


async def _push_drafts_to_integration(user: dict, list_id: int, account_ids: list[int], push_fn):
    """Push drafted sequences to a sequence-based integration (Outreach, SalesLoft)."""
    from database import get_list, get_outreach_draft

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    if account_ids:
        accounts = await get_list_accounts(list_id, account_ids=account_ids, limit=10000)
    else:
        accounts = await get_list_accounts(list_id, status="completed", limit=10000)

    if not accounts:
        raise HTTPException(status_code=400, detail="No accounts to push")

    drafts_by_account = {}
    for account in accounts:
        if account.get("document_id"):
            draft = await get_outreach_draft(account["document_id"])
            if draft and draft.get("content"):
                content = draft["content"]
                if isinstance(content, str):
                    content = json.loads(content)
                emails = content.get("emails", [])
                if emails:
                    drafts_by_account[account["id"]] = emails

    if not drafts_by_account:
        raise HTTPException(status_code=400, detail="No written sequences found. Write sequences first.")

    result = await push_fn(user["id"], accounts, drafts_by_account)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

