"""Setup Cloudflare edge rate limiting rules via the Rulesets API.

Deploys 7 rate limiting rules to the zone's http_ratelimit phase.
Uses PUT (idempotent) — replaces the entire phase ruleset each run.

Usage:
    python3 scripts/setup_cloudflare_rules.py              # deploy rules
    python3 scripts/setup_cloudflare_rules.py --dry-run    # print without deploying
"""

import argparse
import json
import sys

import httpx

import os


API_CHARACTERISTICS = ["cf.colo.id", 'http.request.headers["authorization"]']
IP_CHARACTERISTICS = ["cf.colo.id", "ip.src"]


def build_rules() -> list[dict]:
    """Return the 7 rate limiting rules in evaluation order."""

    def _api_rule(name: str, expression: str, rps: int, period: int, block_secs: int) -> dict:
        return {
            "description": name,
            "expression": expression,
            "action": "block",
            "action_parameters": {
                "response": {
                    "status_code": 429,
                    "content_type": "application/json",
                    "content": json.dumps(
                        {
                            "error": {
                                "code": "rate_limited",
                                "message": f"Rate limit exceeded. Try again in {block_secs} seconds.",
                            }
                        }
                    ),
                },
            },
            "ratelimit": {
                "characteristics": API_CHARACTERISTICS,
                "requests_per_period": rps,
                "period": period,
                "mitigation_timeout": block_secs,
            },
        }

    def _ip_rule(name: str, expression: str, rps: int, period: int, block_secs: int) -> dict:
        return {
            "description": name,
            "expression": expression,
            "action": "block",
            "action_parameters": {
                "response": {
                    "status_code": 429,
                    "content_type": "text/plain",
                    "content": f"Rate limit exceeded. Try again in {block_secs} seconds.",
                },
            },
            "ratelimit": {
                "characteristics": IP_CHARACTERISTICS,
                "requests_per_period": rps,
                "period": period,
                "mitigation_timeout": block_secs,
            },
        }

    return [
        # 1 — Research endpoint
        _api_rule(
            "API: POST /v1/research",
            '(http.request.uri.path eq "/v1/research" and http.request.method eq "POST")',
            10, 60, 60,
        ),
        # 2 — Bulk research
        _api_rule(
            "API: POST /v1/research/bulk",
            '(http.request.uri.path eq "/v1/research/bulk" and http.request.method eq "POST")',
            2, 60, 60,
        ),
        # 3 — Sequence start
        _api_rule(
            "API: POST /v1/research/*/sequence",
            '(http.request.uri.path matches "^/v1/research/[0-9]+/sequence$" and http.request.method eq "POST")',
            20, 60, 60,
        ),
        # 4 — Clay enrichment
        _api_rule(
            "API: POST /v1/clay/enrich",
            '(http.request.uri.path eq "/v1/clay/enrich" and http.request.method eq "POST")',
            5, 60, 60,
        ),
        # 5 — API catch-all
        _api_rule(
            "API: /v1/* catch-all",
            '(starts_with(http.request.uri.path, "/v1/"))',
            60, 60, 60,
        ),
        # 6 — Auth endpoints (by IP)
        _ip_rule(
            "Web: /auth/*",
            '(starts_with(http.request.uri.path, "/auth/"))',
            10, 60, 300,
        ),
        # 7 — List upload (by IP)
        _ip_rule(
            "Web: POST /lists/upload",
            '(http.request.uri.path eq "/lists/upload" and http.request.method eq "POST")',
            3, 60, 60,
        ),
    ]


def deploy_rules(zone_id: str, api_token: str, rules: list[dict], dry_run: bool) -> None:
    """PUT the ruleset to the zone's http_ratelimit phase entrypoint."""
    payload = {
        "name": "Rate limiting rules",
        "kind": "zone",
        "phase": "http_ratelimit",
        "rules": rules,
    }

    if dry_run:
        print("=== DRY RUN — would deploy the following payload ===\n")
        print(json.dumps(payload, indent=2))
        print(f"\n{len(rules)} rule(s) total.")
        return

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/rulesets/phases/http_ratelimit/entrypoint"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    resp = httpx.put(url, json=payload, headers=headers, timeout=30)

    if resp.status_code == 200:
        data = resp.json()
        if data.get("success"):
            ruleset_id = data["result"]["id"]
            print(f"Deployed {len(rules)} rate limiting rule(s).")
            print(f"Ruleset ID: {ruleset_id}")
            return

    # Error handling
    status = resp.status_code
    try:
        body = resp.json()
    except Exception:
        body = resp.text

    if status == 401:
        print(f"Error 401: Invalid API token. Check CLOUDFLARE_API_TOKEN.", file=sys.stderr)
    elif status == 403:
        print(f"Error 403: Insufficient permissions. The token needs Zone > Firewall Services > Edit.", file=sys.stderr)
    elif status == 404:
        print(f"Error 404: Zone not found. Check CLOUDFLARE_ZONE_ID.", file=sys.stderr)
    else:
        print(f"Error {status}: Unexpected response.", file=sys.stderr)

    print(json.dumps(body, indent=2) if isinstance(body, dict) else body, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Cloudflare edge rate limiting rules.")
    parser.add_argument("--dry-run", action="store_true", help="Print rules without deploying")
    args = parser.parse_args()

    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "")

    if not args.dry_run:
        if not api_token:
            print("Error: CLOUDFLARE_API_TOKEN is not set.", file=sys.stderr)
            sys.exit(1)
        if not zone_id:
            print("Error: CLOUDFLARE_ZONE_ID is not set.", file=sys.stderr)
            sys.exit(1)

    rules = build_rules()

    print(f"Rate limiting rules ({len(rules)}):\n")
    for i, rule in enumerate(rules, 1):
        rl = rule["ratelimit"]
        chars = "auth header" if rl["characteristics"] == API_CHARACTERISTICS else "ip.src"
        print(f"  {i}. {rule['description']}")
        print(f"     {rl['requests_per_period']} req / {rl['period']}s, block {rl['mitigation_timeout']}s, key: {chars}")
    print()

    deploy_rules(
        zone_id=zone_id,
        api_token=api_token,
        rules=rules,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
