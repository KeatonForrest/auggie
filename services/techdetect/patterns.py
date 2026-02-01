"""Pattern parsing and version extraction for Wappalyzer pattern syntax."""

import re
from dataclasses import dataclass

# Never-match pattern for invalid regexes
_NEVER_MATCH = re.compile(r"(?!x)x")


@dataclass(frozen=True)
class PreparedPattern:
    regex: "re.Pattern"
    version: str  # template like "\\1" or "\\1?a:b"
    confidence: int


def prepare_pattern(raw: str) -> PreparedPattern:
    """Parse a Wappalyzer pattern string like 'regex\\;version:\\1\\;confidence:80'."""
    parts = raw.split("\\;")
    regex_str = parts[0]
    version = ""
    confidence = 100

    for part in parts[1:]:
        if part.startswith("version:"):
            version = part[len("version:"):]
        elif part.startswith("confidence:"):
            try:
                confidence = int(part[len("confidence:"):])
            except ValueError:
                pass

    try:
        regex = re.compile(regex_str, re.I)
    except re.error:
        regex = _NEVER_MATCH

    return PreparedPattern(regex=regex, version=version, confidence=confidence)


def extract_version(pattern: PreparedPattern, matched_text: str) -> str | None:
    """Extract version string from matched text using the pattern's version template."""
    if not pattern.version:
        return None

    matches = pattern.regex.findall(matched_text)
    if not matches:
        return None

    # findall returns strings for 0-1 groups, tuples for 2+ groups
    match = matches[0]
    if isinstance(match, str):
        groups = (match,)
    else:
        groups = match

    version = pattern.version
    # Handle backreferences and ternary operators
    for i, group in enumerate(groups, 1):
        # Ternary: \N?true_val:false_val
        ternary = re.search(rf"\\{i}\?([^:]*?):(.*?)(?=\\|$)", version)
        if ternary:
            replacement = ternary.group(1) if group else ternary.group(2)
            version = version[:ternary.start()] + replacement + version[ternary.end():]
        else:
            # Simple backreference: \N
            version = version.replace(f"\\{i}", group)

    # Clean up any remaining unresolved backreferences
    version = re.sub(r"\\(\d)", "", version)
    version = version.strip()
    return version if version else None
