#!/usr/bin/env bash
set -euo pipefail

APP_URL="${1:-${APP_URL:-}}"

if [ -z "$APP_URL" ]; then
  echo "Usage: $0 <APP_URL>"
  echo "  or: APP_URL=https://example.com $0"
  exit 1
fi

# Strip trailing slash
APP_URL="${APP_URL%/}"

PASS=0
FAIL=0

check() {
  local name="$1"
  local url="$2"
  local expected="$3"  # comma-separated acceptable status codes
  local follow_mode="$4"
  local status="000"
  local attempt=1
  local max_attempts=5
  local curl_args=(-s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 --retry 2 --retry-all-errors --retry-delay 1 -H "Accept: application/json")

  if [ "$follow_mode" = "follow" ]; then
    curl_args+=(-L)
  fi

  while [ "$attempt" -le "$max_attempts" ]; do
    status=$(curl "${curl_args[@]}" "$url" 2>/dev/null || echo "000")
    if echo "$expected" | grep -qw "$status"; then
      break
    fi
    if [ "$attempt" -lt "$max_attempts" ]; then
      sleep 2
    fi
    attempt=$((attempt + 1))
  done

  # Check if status is in expected list
  if echo "$expected" | grep -qw "$status"; then
    echo "  PASS  $name (HTTP $status)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $name (HTTP $status, expected $expected)"
    FAIL=$((FAIL + 1))
  fi
}

echo "Smoke testing: $APP_URL"
echo "---"

# Health endpoint
check "GET /health" "$APP_URL/health" "200" "follow"

# Root page
check "GET /" "$APP_URL/" "200" "follow"

# Login should redirect (302/307) to OAuth provider
check "GET /auth/login" "$APP_URL/auth/login" "302,307" "no-follow"

# Integrations page — auth-gated, could be 200 (if session), 302 (redirect to login), or 401
check "GET /integrations" "$APP_URL/integrations" "200,302,401" "follow"

# API endpoint without auth should return 401
check "GET /v1/account" "$APP_URL/v1/account" "401,422" "follow"

echo "---"
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
