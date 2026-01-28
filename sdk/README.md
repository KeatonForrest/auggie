# Auggie Python SDK

Python client for the [Auggie](https://auggie.app) account research API.

## Install

```bash
pip install git+https://github.com/your-org/auggie.git#subdirectory=sdk
```

Or for local development:

```bash
cd sdk && pip install -e .
```

## Usage

```python
from auggie import AuggieClient

client = AuggieClient(api_key="aug_your_key_here")

# Submit research and poll until done
result = client.research_and_poll("https://example.com")
print(result["company_name"], result["scores"]["composite"])

# Or submit and poll manually
job = client.research("https://example.com")
status = client.get_research(job["job_id"])

# Generate outreach sequence
sequence = client.create_sequence(doc_id=result["document_id"])
for email in sequence["emails"]:
    print(email["subject"])

# List recent jobs
jobs = client.list_research()

# Webhooks
client.register_webhook("https://yourserver.com/webhook")
client.get_webhook()
client.delete_webhook()
```

## Error handling

```python
from auggie import AuggieClient, AuggieError

try:
    result = client.research("https://example.com")
except AuggieError as e:
    print(e.status_code, e.detail)
```
