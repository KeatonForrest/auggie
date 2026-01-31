"""Pydantic request models for route validation."""

from pydantic import BaseModel


class ApiKeyConnectRequest(BaseModel):
    api_key: str


class HubSpotImportRequest(BaseModel):
    companies: list[dict]
    name: str = "HubSpot Import"


class SalesforceImportRequest(BaseModel):
    accounts: list[dict]
    name: str = "Salesforce Import"


class ZoomInfoImportRequest(BaseModel):
    companies: list[dict]
    name: str = "ZoomInfo Import"


class ApolloImportRequest(BaseModel):
    list_id: str
    name: str = "Apollo Import"


class OceanImportRequest(BaseModel):
    audience_id: str
    name: str = "Ocean.io Import"


class SlackConnectRequest(BaseModel):
    webhook_url: str


class PushCampaignRequest(BaseModel):
    campaign_id: str
    account_ids: list[int] = []


class PushSequencesRequest(BaseModel):
    account_ids: list[int] = []


class AccountIdsRequest(BaseModel):
    account_ids: list[int]


class AutomationCreateRequest(BaseModel):
    name: str
    trigger_event: str
    conditions: dict = {}
    action: str
    action_config: dict = {}


class AutomationToggleRequest(BaseModel):
    enabled: bool = True
