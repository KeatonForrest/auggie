"""Single source of truth for allowed/deprecated integration providers."""

ALLOWED_PROVIDERS = frozenset({"google_sheets", "slack", "teams"})

DEPRECATED_PROVIDERS = frozenset({
    "hubspot", "salesforce", "outreach", "salesloft", "gong_engage",
    "zoominfo", "instantly", "smartlead", "pdl", "lusha", "cognism",
})

DEPRECATED_PROVIDER_NAMES = {
    "hubspot": "HubSpot",
    "salesforce": "Salesforce",
    "outreach": "Outreach",
    "salesloft": "SalesLoft",
    "gong_engage": "Gong Engage",
    "zoominfo": "ZoomInfo",
    "instantly": "Instantly",
    "smartlead": "Smartlead",
    "pdl": "People Data Labs",
    "lusha": "Lusha",
    "cognism": "Cognism",
}

DEPRECATION_MESSAGE = (
    "This integration has been deprecated. "
    "Please use Google Sheets, Slack, or Teams instead."
)
