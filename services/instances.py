"""Shared service singletons — importable from anywhere without circular deps."""

from services.firecrawl import FirecrawlService
from services.claude import ClaudeService
from services.tech_detection import TechDetectionService
from services.writing import WritingService
from services.dns_analyzer import DNSAnalyzer
from services.ssl_analyzer import SSLAnalyzer
from services.job_parser import JobParser
from services.pain_inference import PainInferenceEngine
from services.vision import VisionService

firecrawl_service = FirecrawlService()
claude_service = ClaudeService()
tech_detection_service = TechDetectionService()
writing_service = WritingService()
dns_analyzer = DNSAnalyzer()
ssl_analyzer = SSLAnalyzer()
job_parser = JobParser()
pain_engine = PainInferenceEngine()
vision_service = VisionService()
