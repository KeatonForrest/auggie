# Cloudflare Configuration

Recommended Cloudflare settings for production deployment.

## DNS

- Enable the orange cloud (proxy) on all A/AAAA/CNAME records pointing to the app
- This hides the origin IP and routes traffic through Cloudflare

## SSL/TLS

- SSL mode: **Full (Strict)**
- Minimum TLS version: 1.2
- Always Use HTTPS: ON
- Automatic HTTPS Rewrites: ON

## WAF Rules

Create custom WAF rules to protect API endpoints:

1. **Block non-API traffic to /v1/**: Match `URI Path starts with /v1/` and require `Authorization` header present
2. **Rate limit auth endpoints**: Match `/auth/` paths, limit to 10 requests/minute per IP
3. **Block suspicious user agents**: Block empty or known-malicious user agents

## Rate Limiting

Edge rate limiting rules (applied before requests reach origin):

| Rule | Path | Threshold | Period | Action |
|------|------|-----------|--------|--------|
| API rate limit | `/v1/*` | 60 requests | 1 minute | Block for 60s |
| Auth rate limit | `/auth/*` | 10 requests | 1 minute | Block for 300s |
| Upload rate limit | `/lists/upload` | 5 requests | 1 minute | Block for 60s |

## Cache Rules

- **Static assets** (`/static/*`): Cache Everything, Edge TTL 1 day
- **API responses**: Bypass Cache (default for POST/DELETE, but explicitly set for GET API routes)
- **HTML pages**: Bypass Cache (dynamic, auth-dependent)

## Page Rules

1. `*auggie.app/*` -> Always Use HTTPS
2. `*auggie.app/static/*` -> Cache Level: Cache Everything, Edge Cache TTL: 1 day

## Additional Settings

- **Bot Fight Mode**: ON
- **Browser Integrity Check**: ON
- **Hotlink Protection**: ON (if serving images)
- **Email Address Obfuscation**: ON
