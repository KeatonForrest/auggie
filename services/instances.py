"""Shared service singletons — importable from anywhere without circular deps."""

from services.firecrawl import FirecrawlService
from services.claude import ClaudeService
from services.wappalyzer import WappalyzerService
from services.writing import WritingService

firecrawl_service = FirecrawlService()
claude_service = ClaudeService()
wappalyzer_service = WappalyzerService()
writing_service = WritingService()
