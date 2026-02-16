"""List routes: CSV upload, list view, export, bulk actions, retry, pipeline status, push-to integrations."""

import csv
import re
import logging
from io import StringIO, BytesIO

from fastapi import APIRouter, HTTPException, Request, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse

from auth import require_auth, require_onboarding
from database import (
    get_user_usage, use_credit, refund_credit,
    get_enriched_contacts, get_contact_counts_for_list,
    create_list, add_list_accounts, update_list_credits,
    list_lists, get_list, get_list_accounts, delete_list,
    get_pipeline_counts, count_ready_accounts,
    get_list_account, reset_list_account,
    get_integration, update_list_account,
)
from db.jobs import create_job_with_credit, create_research_job
from api.validation import validate_company_url
from api.tasks import create_tracked_task
from routes._helpers import normalize_url, templates, logger
from routes.integrations_constants import DEPRECATION_MESSAGE
from routes.schemas import AccountIdsRequest
from db.outreach import get_outreach_drafts_batch

router = APIRouter()


def _deprecated_response(provider: str):
    """Return a 410 Gone response for deprecated integrations."""
    return JSONResponse(
        status_code=410,
        content={"error": {"code": "provider_deprecated", "message": f"{provider}: {DEPRECATION_MESSAGE}"}},
    )


@router.get("/lists", response_class=HTMLResponse)
async def lists_page(request: Request, user: dict = Depends(require_onboarding)):
    """Upload page + table of user's recent lists."""
    usage = await get_user_usage(user["id"])
    recent = await list_lists(user["id"])
    gsheets_integration = await get_integration(user["id"], "google_sheets")
    apollo_integration = await get_integration(user["id"], "apollo")
    return templates.TemplateResponse(
        request,
        "lists.html",
        {
            "user": user,
            "lists": recent,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "google_sheets_connected": gsheets_integration is not None,
            "apollo_connected": apollo_integration is not None,
            "zoominfo_connected": False,
            "pdl_connected": False,
            "lusha_connected": False,
            "cognism_connected": False,
        }
    )


@router.post("/lists/import-google-sheet")
async def import_google_sheet(
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Import rows from a Google Sheets URL, same logic as CSV upload."""
    from api.ratelimit import upload_limiter, get_client_ip
    from api.jobs import run_list_analysis
    from services.google_sheets import extract_spreadsheet_id, fetch_sheet_rows
    from routes.schemas import GoogleSheetsImportRequest

    upload_limiter.check(get_client_ip(request))

    body = GoogleSheetsImportRequest(**(await request.json()))
    spreadsheet_id = extract_spreadsheet_id(body.url)
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Invalid Google Sheets URL.")

    try:
        rows = await fetch_sheet_rows(user["id"], spreadsheet_id)
    except Exception as e:
        logger.error("Google Sheets API error: %s", e)
        raise HTTPException(status_code=502, detail="Failed to read Google Sheet. Make sure it's shared or you've connected Google Sheets.")

    if not rows:
        raise HTTPException(status_code=400, detail="Sheet is empty.")

    # Detect domain column (same logic as CSV upload)
    header = rows[0]
    domain_col = None
    recognized = {"domain", "url", "website", "company_url", "company"}
    for i, col in enumerate(header):
        if col.strip().lower() in recognized:
            domain_col = i
            break

    if domain_col is not None:
        data_rows = rows[1:]
    else:
        domain_col = 0
        data_rows = rows

    raw_urls = []
    for row in data_rows:
        if domain_col < len(row) and row[domain_col].strip():
            raw_urls.append(row[domain_col].strip())

    valid_urls = []
    seen = set()
    for raw in raw_urls:
        url = normalize_url(raw)
        try:
            url = validate_company_url(url)
        except ValueError:
            continue
        if url not in seen:
            seen.add(url)
            valid_urls.append(url)
        if len(valid_urls) >= 100:
            break

    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid domains found in the sheet.")

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(valid_urls) * 100
    if not is_admin and usage.get("bonus_credits", 0) < needed:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. Need {len(valid_urls)}, have {usage.get('bonus_credits', 0) // 100}."
        )

    if not is_admin:
        ok = await use_credit(user["id"], cents=needed)
        if not ok:
            raise HTTPException(status_code=402, detail="Not enough credits.")

    name = body.list_name.strip() or "Google Sheets Import"
    lst = await create_list(user["id"], api_key_id=None, name=name, org_id=user.get("org_id"))
    await add_list_accounts(lst["id"], valid_urls)
    await update_list_credits(lst["id"], needed)

    await create_tracked_task("list_analysis", {"list_id": lst["id"], "user_id": user["id"], "api_key_id": None, "is_admin": is_admin}, name=f"list-{lst['id']}")

    return JSONResponse({"success": True, "list_id": lst["id"]})


@router.post("/lists/upload")
async def upload_list_csv(
    request: Request,
    file: UploadFile = File(...),
    list_name: str = Form(""),
    user: dict = Depends(require_onboarding),
):
    """Parse CSV, validate URLs, check credits, create list, start analysis."""
    from api.ratelimit import upload_limiter, get_client_ip
    from api.jobs import run_list_analysis

    upload_limiter.check(get_client_ip(request))

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="Please upload a .csv, .xlsx, or .xls file.")
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("csv", "xlsx", "xls"):
        raise HTTPException(status_code=400, detail="Please upload a .csv, .xlsx, or .xls file.")

    contents = await file.read()
    if len(contents) > 1_048_576:
        raise HTTPException(status_code=400, detail="File too large (max 1MB).")

    # Parse file into rows
    if ext in ("xlsx", "xls"):
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(contents), read_only=True, data_only=True)
        ws = wb.active
        rows = [[str(cell) if cell is not None else "" for cell in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        text = contents.decode("utf-8", errors="replace")
        reader = csv.reader(StringIO(text))
        rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV file is empty.")

    # Detect domain column
    header = rows[0]
    domain_col = None
    recognized = {"domain", "url", "website", "company_url", "company"}
    for i, col in enumerate(header):
        if col.strip().lower() in recognized:
            domain_col = i
            break

    if domain_col is not None:
        data_rows = rows[1:]  # skip header
    else:
        domain_col = 0  # treat first column as domains
        # If first row looks like a URL/domain, include it
        data_rows = rows

    # Extract and normalize URLs
    raw_urls = []
    for row in data_rows:
        if domain_col < len(row) and row[domain_col].strip():
            raw_urls.append(row[domain_col].strip())

    # Normalize and validate
    valid_urls = []
    seen = set()
    for raw in raw_urls:
        url = normalize_url(raw)
        try:
            url = validate_company_url(url)
        except ValueError:
            continue
        if url not in seen:
            seen.add(url)
            valid_urls.append(url)
        if len(valid_urls) >= 100:
            break

    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid domains found in CSV.")

    # Check credits
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(valid_urls) * 100  # cents
    if not is_admin and usage.get("bonus_credits", 0) < needed:
        raise HTTPException(
            status_code=402,
            detail=f"Not enough credits. Need {len(valid_urls)}, have {usage.get('bonus_credits', 0) // 100}."
        )

    # Reserve credits atomically
    if not is_admin:
        ok = await use_credit(user["id"], cents=needed)
        if not ok:
            raise HTTPException(status_code=402, detail=f"Not enough credits.")

    # Create list
    name = list_name.strip() or (file.filename.rsplit(".", 1)[0] if file.filename else "Uploaded List")
    lst = await create_list(user["id"], api_key_id=None, name=name, org_id=user.get("org_id"))
    await add_list_accounts(lst["id"], valid_urls)
    await update_list_credits(lst["id"], needed)

    # Start analysis in background
    await create_tracked_task("list_analysis", {"list_id": lst["id"], "user_id": user["id"], "api_key_id": None, "is_admin": is_admin}, name=f"list-{lst['id']}")

    return RedirectResponse(url=f"/lists/{lst['id']}", status_code=303)


@router.get("/lists/{list_id}", response_class=HTMLResponse)
async def view_list(
    request: Request,
    list_id: int,
    min_score: int = 0,
    sort: str = "composite_score",
    user: dict = Depends(require_onboarding),
):
    """Results page with sortable/filterable score table."""
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    accounts = await get_list_accounts(
        list_id,
        min_composite=min_score if min_score > 0 else None,
        sort_by=sort,
    )
    usage = await get_user_usage(user["id"])

    # Check if integrations are connected
    gsheets_integration = await get_integration(user["id"], "google_sheets")
    apollo_integration = await get_integration(user["id"], "apollo")

    # Contact counts per account (single SQL query)
    contact_counts = await get_contact_counts_for_list(list_id, user["id"])

    # Pipeline step counts (single SQL query)
    counts = await get_pipeline_counts(list_id)
    scored_count = counts["scored"]
    enriched_count = counts["enriched"]
    written_count = counts["sequences_written"]
    pushed_count = counts["pushed"]

    return templates.TemplateResponse(
        request,
        "list_view.html",
        {
            "user": user,
            "list": lst,
            "accounts": accounts,
            "min_score": min_score,
            "sort": sort,
            "credits": usage.get("bonus_credits", 0) / 100,
            "is_admin": usage.get("is_admin", False),
            "instantly_connected": False,
            "smartlead_connected": False,
            "outreach_connected": False,
            "salesloft_connected": False,
            "apollo_connected": apollo_integration is not None,
            "gong_engage_connected": False,
            "google_sheets_connected": gsheets_integration is not None,
            "scored_count": scored_count,
            "enriched_count": enriched_count,
            "written_count": written_count,
            "pushed_count": pushed_count,
            "contact_counts": contact_counts,
        }
    )


@router.get("/lists/{list_id}/export")
async def export_list_csv(
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Export list accounts as CSV."""
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    accounts = await get_list_accounts(list_id, limit=10000)

    # Batch-fetch outreach drafts
    doc_ids = [a["document_id"] for a in accounts if a.get("document_id")]
    drafts = await get_outreach_drafts_batch(doc_ids) if doc_ids else {}

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Company Name", "Website", "Pain Score", "Fit Score", "Timing Score", "Composite Score", "Status", "Email Subject", "Email 1 Body", "Email 2 Body", "Email 3 Body"])
    for a in accounts:
        draft = drafts.get(a.get("document_id")) or {}
        emails = draft.get("emails", [])
        writer.writerow([
            a.get("company_name") or "",
            a.get("company_url", ""),
            a.get("pain_score") if a.get("pain_score") is not None else "",
            a.get("fit_score") if a.get("fit_score") is not None else "",
            a.get("timing_score") if a.get("timing_score") is not None else "",
            a.get("composite_score") if a.get("composite_score") is not None else "",
            a.get("status", ""),
            draft.get("subject", ""),
            emails[0].get("body", "") if len(emails) > 0 else "",
            emails[1].get("body", "") if len(emails) > 1 else "",
            emails[2].get("body", "") if len(emails) > 2 else "",
        ])

    safe_name = re.sub(r'[^\w\s\-.]', '', lst["name"])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
    )


@router.get("/lists/{list_id}/export-apollo")
async def export_apollo_csv(
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Export contact-level CSV for Apollo import with personalized email content."""
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    accounts = await get_list_accounts(list_id, limit=10000)

    doc_ids = [a["document_id"] for a in accounts if a.get("document_id")]
    drafts = await get_outreach_drafts_batch(doc_ids) if doc_ids else {}

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "first_name", "last_name", "email", "title", "linkedin_url",
        "company_name", "company_url",
        "auggie_composite_score", "auggie_pain_score", "auggie_fit_score", "auggie_timing_score",
        "auggie_email_1_subject", "auggie_email_1_body",
        "auggie_email_2_subject", "auggie_email_2_body",
        "auggie_email_3_subject", "auggie_email_3_body",
    ])

    for a in accounts:
        doc_id = a.get("document_id")
        if not doc_id:
            continue
        contacts = await get_enriched_contacts(doc_id, user["id"])
        draft = drafts.get(doc_id) or {}
        emails = draft.get("emails", [])
        for c in contacts:
            if not c.get("email"):
                continue
            writer.writerow([
                c.get("first_name", ""),
                c.get("last_name", ""),
                c.get("email", ""),
                c.get("title", ""),
                c.get("profile_url", ""),
                a.get("company_name", ""),
                a.get("company_url", ""),
                a.get("composite_score") if a.get("composite_score") is not None else "",
                a.get("pain_score") if a.get("pain_score") is not None else "",
                a.get("fit_score") if a.get("fit_score") is not None else "",
                a.get("timing_score") if a.get("timing_score") is not None else "",
                emails[0].get("subject", "") if len(emails) > 0 else "",
                emails[0].get("body", "") if len(emails) > 0 else "",
                emails[1].get("subject", "") if len(emails) > 1 else "",
                emails[1].get("body", "") if len(emails) > 1 else "",
                emails[2].get("subject", "") if len(emails) > 2 else "",
                emails[2].get("body", "") if len(emails) > 2 else "",
            ])

    safe_name = re.sub(r'[^\w\s\-.]', '', lst["name"])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_apollo.csv"'},
    )


@router.post("/lists/{list_id}/export-selected")
async def export_selected_csv(
    list_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Export selected list accounts as CSV."""
    body = await request.json()
    account_ids = body.get("account_ids", [])
    if not account_ids:
        raise HTTPException(status_code=400, detail="No accounts selected")

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    selected = await get_list_accounts(list_id, account_ids=account_ids, limit=10000)

    # Batch-fetch outreach drafts
    doc_ids = [a["document_id"] for a in selected if a.get("document_id")]
    drafts = await get_outreach_drafts_batch(doc_ids) if doc_ids else {}

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Company Name", "Website", "Pain Score", "Fit Score", "Timing Score", "Composite Score", "Status", "Email Subject", "Email 1 Body", "Email 2 Body", "Email 3 Body"])
    for a in selected:
        draft = drafts.get(a.get("document_id")) or {}
        emails = draft.get("emails", [])
        writer.writerow([
            a.get("company_name") or "",
            a.get("company_url", ""),
            a.get("pain_score") if a.get("pain_score") is not None else "",
            a.get("fit_score") if a.get("fit_score") is not None else "",
            a.get("timing_score") if a.get("timing_score") is not None else "",
            a.get("composite_score") if a.get("composite_score") is not None else "",
            a.get("status", ""),
            draft.get("subject", ""),
            emails[0].get("body", "") if len(emails) > 0 else "",
            emails[1].get("body", "") if len(emails) > 1 else "",
            emails[2].get("body", "") if len(emails) > 2 else "",
        ])

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="selected_accounts.csv"'},
    )


@router.post("/lists/{list_id}/push-to-sheets")
async def push_to_sheets(
    list_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Push list data + sequences to a new Google Spreadsheet."""
    from services.google_sheets import create_and_write_sheet

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    integration = await get_integration(user["id"], "google_sheets")
    if not integration:
        raise HTTPException(status_code=400, detail="Google Sheets not connected")

    try:
        body = await request.json()
    except Exception:
        body = {}
    account_ids = body.get("account_ids")

    accounts = await get_list_accounts(list_id, account_ids=account_ids, limit=10000)

    # Batch-fetch outreach drafts
    doc_ids = [a["document_id"] for a in accounts if a.get("document_id")]
    drafts = await get_outreach_drafts_batch(doc_ids) if doc_ids else {}

    header = ["Company Name", "Website", "Pain Score", "Fit Score", "Timing Score", "Composite Score", "Status", "Email Subject", "Email 1 Body", "Email 2 Body", "Email 3 Body"]
    rows = []
    for a in accounts:
        draft = drafts.get(a.get("document_id")) or {}
        emails = draft.get("emails", [])
        rows.append([
            a.get("company_name") or "",
            a.get("company_url", ""),
            str(a.get("pain_score", "")),
            str(a.get("fit_score", "")),
            str(a.get("timing_score", "")),
            str(a.get("composite_score", "")),
            a.get("status", ""),
            draft.get("subject", ""),
            emails[0].get("body", "") if len(emails) > 0 else "",
            emails[1].get("body", "") if len(emails) > 1 else "",
            emails[2].get("body", "") if len(emails) > 2 else "",
        ])

    title = f"Auggie - {lst['name']}"
    try:
        spreadsheet_url = await create_and_write_sheet(user["id"], title, header, rows)
    except Exception as e:
        logger.error("Google Sheets push failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to create Google Sheet. You may need to reconnect Google Sheets.")

    return JSONResponse({"success": True, "spreadsheet_url": spreadsheet_url})


@router.post("/lists/{list_id}/batch-write-sequences")
async def batch_write_sequences(
    list_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Generate outreach sequences for accounts in a list."""
    from api.jobs import run_batch_write_sequences

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    try:
        body = await request.json()
    except Exception:
        body = {}
    account_ids = body.get("account_ids")

    await create_tracked_task(
        "batch_write",
        {"list_id": list_id, "user_id": user["id"], "account_ids": account_ids},
        name=f"write-seq-{list_id}",
    )

    # Count how many will be processed
    queued = await count_ready_accounts(list_id, account_ids=account_ids)

    return JSONResponse({"success": True, "queued_count": queued})


@router.post("/lists/{list_id}/batch-enrich")
async def batch_enrich(
    list_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Batch enrich contacts for accounts in a list using connected providers."""
    from services.enrichment import get_provider_priority

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    # Check user has at least one enrichment provider connected
    providers = await get_provider_priority(user["id"])
    if not providers:
        return JSONResponse(
            {"success": False, "error": "No enrichment provider connected. Connect Apollo or another provider in Integrations."},
            status_code=422,
        )

    try:
        body = await request.json()
    except Exception:
        body = {}
    account_ids = body.get("account_ids")

    await create_tracked_task(
        "batch_enrich",
        {"list_id": list_id, "user_id": user["id"], "account_ids": account_ids},
        name=f"enrich-{list_id}",
    )

    queued = await count_ready_accounts(list_id, account_ids=account_ids)
    return JSONResponse({"success": True, "queued_count": queued})


@router.get("/lists/{list_id}/pipeline-status")
async def pipeline_status(
    list_id: int,
    user: dict = Depends(require_auth),
):
    """Get pipeline step counts for a list."""
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    counts = await get_pipeline_counts(list_id)

    # Auto-finalize if all accounts are done but list status is stale
    if lst.get("status") in ("created", "analyzing") and counts["total"] > 0:
        # Use actual account statuses rather than the list-level counter which can get out of sync
        done_accounts = counts["scored"] + counts.get("failed", 0)
        if done_accounts >= counts["total"]:
            from database import finalize_list
            lst = await finalize_list(list_id)

    return JSONResponse({
        "scored": counts["scored"],
        "enriched": counts["enriched"],
        "sequences_written": counts["sequences_written"],
        "pushed": counts["pushed"],
        "total": counts["total"],
        "list_status": lst.get("status", "unknown"),
        "processed": lst.get("analyzed_accounts", 0) + lst.get("failed_accounts", 0),
        "failed": lst.get("failed_accounts", 0),
    })


@router.post("/lists/{list_id}/delete")
async def delete_list_route(
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Delete a list and all its accounts, redirect to /lists."""
    deleted = await delete_list(list_id, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="List not found")
    return RedirectResponse(url="/lists", status_code=303)


@router.post("/lists/{list_id}/retry-selected")
async def retry_selected_accounts(
    list_id: int,
    request: Request,
    user: dict = Depends(require_onboarding),
):
    """Retry multiple failed list accounts."""
    body = AccountIdsRequest(**(await request.json()))
    if not body.account_ids:
        return JSONResponse({"success": False, "error": "No accounts selected"}, status_code=400)

    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    failed = await get_list_accounts(list_id, status="failed", account_ids=body.account_ids, limit=10000)

    if not failed:
        return JSONResponse({"success": False, "error": "No failed accounts in selection"}, status_code=400)

    # Reserve credits atomically
    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    needed = len(failed) * 100
    if not is_admin:
        ok = await use_credit(user["id"], cents=needed)
        if not ok:
            return JSONResponse({"success": False, "error": "Not enough credits"}, status_code=402)

    # Reset and start retries
    retried = 0
    for a in failed:
        await reset_list_account(a["id"])
        job = await create_research_job(user["id"], api_key_id=None, company_url=a["company_url"])
        await update_list_account(a["id"], "processing", research_job_id=job["id"])

        await create_tracked_task(
            "retry",
            {"user_id": user["id"], "account_id": a["id"], "company_url": a["company_url"], "job_id": job["id"], "is_admin": is_admin},
            name=f"retry-{a['id']}",
        )
        retried += 1

    return JSONResponse({"success": True, "retried": retried})


@router.post("/lists/{list_id}/accounts/{account_id}/retry")
async def retry_list_account(
    list_id: int,
    account_id: int,
    user: dict = Depends(require_onboarding),
):
    """Retry a failed list account."""
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    account = await get_list_account(account_id, list_id)
    if not account:
        return JSONResponse({"success": False, "error": "Account not found"}, status_code=404)
    if account["status"] != "failed":
        return JSONResponse({"success": False, "error": "Account is not in failed state"}, status_code=400)

    usage = await get_user_usage(user["id"])
    is_admin = usage.get("is_admin", False)
    if not is_admin:
        try:
            job = await create_job_with_credit(user["id"], api_key_id=None, company_url=account["company_url"])
        except ValueError:
            return JSONResponse({"success": False, "error": "No credits remaining."}, status_code=402)
    else:
        job = await create_research_job(user["id"], api_key_id=None, company_url=account["company_url"])

    await reset_list_account(account_id)
    await update_list_account(account_id, "processing", research_job_id=job["id"])

    await create_tracked_task(
        "retry",
        {"user_id": user["id"], "account_id": account_id, "company_url": account["company_url"], "job_id": job["id"], "is_admin": is_admin},
        name=f"retry-{account_id}",
    )
    return JSONResponse({"success": True})


@router.get("/lists/{list_id}/accounts/{account_id}/contacts")
async def get_account_contacts(
    list_id: int,
    account_id: int,
    user: dict = Depends(require_auth),
):
    """Return enriched contacts for a list account."""
    lst = await get_list(list_id, user["id"])
    if not lst:
        raise HTTPException(status_code=404, detail="List not found")

    account = await get_list_account(account_id, list_id)
    if not account or not account.get("document_id"):
        return JSONResponse({"contacts": []})

    contacts = await get_enriched_contacts(account["document_id"], user["id"])
    return JSONResponse({
        "contacts": [
            {
                "first_name": c.get("first_name", ""),
                "last_name": c.get("last_name", ""),
                "title": c.get("title", ""),
                "email": c.get("email", ""),
                "profile_url": c.get("profile_url", ""),
            }
            for c in contacts
        ]
    })


# ==========================================================================
# Push-to-integration routes
# ==========================================================================

@router.post("/lists/{list_id}/push-instantly")
async def push_to_instantly(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Push selected accounts from a list to an Instantly campaign."""
    return _deprecated_response("instantly")


@router.post("/lists/{list_id}/push-smartlead")
async def push_to_smartlead(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Push selected accounts from a list to a Smartlead campaign."""
    return _deprecated_response("smartlead")


@router.post("/lists/{list_id}/push-instantly-campaign")
async def push_to_instantly_campaign(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Bulk create Instantly campaigns with Auggie-generated sequences."""
    return _deprecated_response("instantly")


@router.post("/lists/{list_id}/push-smartlead-campaign")
async def push_to_smartlead_campaign(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Bulk create Smartlead campaigns with Auggie-generated sequences."""
    return _deprecated_response("smartlead")


@router.post("/lists/{list_id}/push-outreach")
async def push_to_outreach(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Push Auggie-generated sequences to Outreach (sequences only, no contacts)."""
    return _deprecated_response("outreach")


@router.post("/lists/{list_id}/push-salesloft")
async def push_to_salesloft(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Push Auggie-generated sequences to SalesLoft as cadences (no contacts)."""
    return _deprecated_response("salesloft")


@router.post("/lists/{list_id}/push-gong-engage")
async def push_to_gong_engage(
    request: Request,
    list_id: int,
    user: dict = Depends(require_onboarding),
):
    """Push Auggie-generated sequences to a Gong Engage flow with content overrides."""
    return _deprecated_response("gong_engage")
