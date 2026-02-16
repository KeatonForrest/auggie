# Auggie Python SDK

Python client for the [Auggie](https://auggie.tools) account research API.

## Install

```bash
pip install git+https://github.com/KeatonForrest/auggie.git#subdirectory=sdk
```

Or for local development:

```bash
cd sdk && pip install -e .
```

## Quick start

```python
from auggie import AuggieClient

client = AuggieClient(api_key="sk_live_your_key_here")

# Submit research and poll until done
result = client.research_and_poll("https://example.com")
print(result["company_name"], result["scores"]["composite"])

# Or submit and poll manually
job = client.research("https://example.com")
status = client.get_research(job["job_id"])
```

## Account

```python
client.ping()           # Health check
client.get_account()    # Credits, subscription, org info
```

## Research & enrichment

```python
# List recent jobs (with pagination)
jobs = client.list_research(limit=50, offset=0)

# Enrich contacts for a completed document
contacts = client.enrich(document_id=42, titles=["CTO", "VP Engineering"])

# Clay-optimized sync enrichment (extended timeout)
clay_result = client.clay_enrich("https://example.com")

# Generate outreach sequence
sequence = client.create_sequence(doc_id=42)
for email in sequence["emails"]:
    print(email["subject"])
```

## Bulk research

```python
bulk = client.bulk_research(["https://a.com", "https://b.com"], name="Q1 targets")
status = client.get_bulk_job(bulk["bulk_job_id"])
all_jobs = client.list_bulk_jobs(limit=20)
```

## Lists

```python
lst = client.create_list("Top accounts", ["https://a.com", "https://b.com"])
details = client.get_list(lst["list_id"], min_pain_score=60, sort_by="pain_score")
all_lists = client.list_lists(limit=50)
client.analyze_list(lst["list_id"])
client.push_list(lst["list_id"], campaign_id="camp_123")
client.delete_list(lst["list_id"])
```

## Team management

```python
members = client.list_team()
client.invite_member("new@company.com", role="member")
client.change_member_role(member_id=5, role="admin")
client.remove_member(member_id=5)
```

## Watchlist

```python
item = client.add_to_watchlist("https://example.com", schedule="weekly")
items = client.list_watchlist(limit=50)
client.update_watchlist(item["id"], schedule="monthly")
history = client.get_watchlist_history(item["id"])
client.remove_from_watchlist(item["id"])
```

## Webhooks

```python
client.register_webhook("https://yourserver.com/webhook")
client.get_webhook()
client.delete_webhook()
```

## Async usage

```python
import asyncio
from auggie import AsyncAuggieClient

async def main():
    async with AsyncAuggieClient(api_key="sk_live_your_key_here") as client:
        result = await client.research_and_poll("https://example.com")
        print(result["company_name"])

        # All methods from AuggieClient are available as async
        account = await client.get_account()
        items = await client.list_watchlist()

asyncio.run(main())
```

## Error handling

```python
from auggie import AuggieClient, AuggieError

try:
    result = client.research("https://example.com")
except AuggieError as e:
    print(e.status_code)  # 402
    print(e.code)         # "insufficient_credits"
    print(e.message)      # "No credits remaining"
    print(e.detail)       # same as e.message (backward compat)
```
