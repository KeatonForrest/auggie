"""Core technology detection engine. Thread-safe, stateless per-analysis."""

import re
from dataclasses import dataclass, field
from services.techdetect.fingerprints import load_fingerprints, Technology
from services.techdetect.patterns import extract_version


@dataclass
class DetectionResult:
    name: str
    versions: set = field(default_factory=set)
    confidence: int = 0
    categories: list = field(default_factory=list)


class TechDetector:
    """Drop-in replacement for python-Wappalyzer's Wappalyzer class."""

    def __init__(self, path: str | None = None):
        self.technologies, self.categories = load_fingerprints(path)

    def analyze(self, webpage) -> dict[str, DetectionResult]:
        """Analyze a webpage and return detected technologies."""
        detected: dict[str, DetectionResult] = {}

        for name, tech in self.technologies.items():
            result = self._check_technology(tech, webpage)
            if result is not None:
                detected[name] = result

        self._resolve_implies(detected)
        return detected

    def _check_technology(self, tech: Technology, webpage) -> DetectionResult | None:
        """Check if a technology matches the webpage. Returns DetectionResult or None."""
        result = DetectionResult(name=tech.name)
        matched = False

        # URL patterns
        for pattern in tech.url_patterns:
            if pattern.regex.search(webpage.url):
                matched = True
                result.confidence = max(result.confidence, pattern.confidence)
                ver = extract_version(pattern, webpage.url)
                if ver:
                    result.versions.add(ver)

        # Header patterns
        for header_name, pattern in tech.header_patterns:
            header_val = webpage.headers.get(header_name, "")
            if header_val and pattern.regex.search(header_val):
                matched = True
                result.confidence = max(result.confidence, pattern.confidence)
                ver = extract_version(pattern, header_val)
                if ver:
                    result.versions.add(ver)

        # Cookie patterns
        for cookie_name, pattern in tech.cookie_patterns:
            cookie_val = webpage.cookies.get(cookie_name, "")
            if cookie_val and pattern.regex.search(cookie_val):
                matched = True
                result.confidence = max(result.confidence, pattern.confidence)
                ver = extract_version(pattern, cookie_val)
                if ver:
                    result.versions.add(ver)

        # Script patterns
        for pattern in tech.script_patterns:
            for script_src in webpage.scripts:
                if pattern.regex.search(script_src):
                    matched = True
                    result.confidence = max(result.confidence, pattern.confidence)
                    ver = extract_version(pattern, script_src)
                    if ver:
                        result.versions.add(ver)

        # Inline script patterns
        for js_global, pattern in tech.inline_script_patterns:
            if pattern.regex.search(webpage.inline_scripts):
                matched = True
                result.confidence = max(result.confidence, pattern.confidence)
                ver = extract_version(pattern, webpage.inline_scripts)
                if ver:
                    result.versions.add(ver)

        # Meta patterns
        for meta_name, pattern in tech.meta_patterns:
            meta_val = webpage.meta.get(meta_name, "")
            if meta_val and pattern.regex.search(meta_val):
                matched = True
                result.confidence = max(result.confidence, pattern.confidence)
                ver = extract_version(pattern, meta_val)
                if ver:
                    result.versions.add(ver)

        # HTML patterns (most expensive — check last)
        for pattern in tech.html_patterns:
            if pattern.regex.search(webpage.html):
                matched = True
                result.confidence = max(result.confidence, pattern.confidence)
                ver = extract_version(pattern, webpage.html)
                if ver:
                    result.versions.add(ver)

        if not matched:
            return None

        # Resolve categories
        result.categories = [
            self.categories.get(str(cat_id), f"Category {cat_id}")
            for cat_id in tech.cats
        ]

        return result

    def _resolve_implies(self, detected: dict[str, DetectionResult]):
        """Resolve implied technologies using breadth-first expansion."""
        queue = list(detected.keys())
        seen = set(queue)

        while queue:
            name = queue.pop(0)
            tech = self.technologies.get(name)
            if not tech:
                continue

            for implied_raw in tech.implies:
                # Parse confidence from implies: "Tech\\;confidence:50"
                parts = implied_raw.split("\\;")
                implied_name = parts[0]
                confidence = 100
                for part in parts[1:]:
                    if part.startswith("confidence:"):
                        try:
                            confidence = int(part[len("confidence:"):])
                        except ValueError:
                            pass

                # Apply parent confidence
                parent_confidence = detected[name].confidence if name in detected else 100
                effective_confidence = min(confidence, parent_confidence)

                if effective_confidence < 50:
                    continue

                if implied_name in detected:
                    detected[implied_name].confidence = max(
                        detected[implied_name].confidence, effective_confidence
                    )
                elif implied_name in self.technologies:
                    implied_tech = self.technologies[implied_name]
                    detected[implied_name] = DetectionResult(
                        name=implied_name,
                        confidence=effective_confidence,
                        categories=[
                            self.categories.get(str(c), f"Category {c}")
                            for c in implied_tech.cats
                        ],
                    )

                if implied_name not in seen:
                    seen.add(implied_name)
                    queue.append(implied_name)

    def analyze_with_versions_and_categories(self, webpage) -> dict:
        """Compatibility shim returning the dict format WappalyzerService expects."""
        detected = self.analyze(webpage)
        result = {}
        for name, det in detected.items():
            result[name] = {
                "versions": sorted(det.versions),
                "categories": det.categories,
            }
        return result
