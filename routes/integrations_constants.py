"""Single source of truth for allowed/deprecated integration providers."""

ALLOWED_PROVIDERS = frozenset({"apollo", "google_sheets", "slack", "teams"})

DEPRECATED_PROVIDERS = frozenset({
    "hubspot", "salesforce", "outreach", "salesloft", "gong_engage",
    "zoominfo", "instantly", "smartlead", "pdl", "lusha", "cognism",
})

DEPRECATION_MESSAGE = (
    "This integration has been deprecated. "
    "Please use Apollo, Google Sheets, Slack, or Teams instead."
)
