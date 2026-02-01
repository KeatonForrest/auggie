"""Custom technology detection engine — drop-in replacement for python-Wappalyzer."""

from services.techdetect.detector import TechDetector
from services.techdetect.webpage import WebPage

__all__ = ["TechDetector", "WebPage"]
