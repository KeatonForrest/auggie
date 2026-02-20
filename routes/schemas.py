"""Pydantic request models for route validation."""

from pydantic import BaseModel


class ApiKeyConnectRequest(BaseModel):
    api_key: str


class GoogleSheetsImportRequest(BaseModel):
    url: str
    list_name: str = "Google Sheets Import"


class SlackConnectRequest(BaseModel):
    webhook_url: str


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
