"""HTML page representation for technology detection."""

import requests
from bs4 import BeautifulSoup


class WebPage:
    """Represents a web page for technology detection."""

    def __init__(self, url: str, html: str, headers: dict | None = None):
        self.url = url
        self.html = html
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.scripts: list[str] = []
        self.meta: dict[str, str] = {}
        self._parse_html()

    def _parse_html(self):
        soup = BeautifulSoup(self.html, "lxml")
        self.scripts = [
            tag["src"] for tag in soup.find_all("script", src=True)
        ]
        for tag in soup.find_all("meta"):
            name = tag.get("name") or tag.get("property") or ""
            content = tag.get("content") or ""
            if name:
                self.meta[name.lower()] = content

    @classmethod
    def new_from_url(cls, url: str, **kwargs) -> "WebPage":
        response = requests.get(url, timeout=10, **kwargs)
        return cls(url, response.text, dict(response.headers))
