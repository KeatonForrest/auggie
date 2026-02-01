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
        self.inline_scripts: str = ""
        self.cookies: dict[str, str] = {}
        # Parse cookies from set-cookie header
        raw_cookie = self.headers.get("set-cookie", "")
        if raw_cookie:
            for cookie_part in raw_cookie.split(","):
                cookie_part = cookie_part.strip()
                if "=" in cookie_part:
                    # Take only the name=value, strip attributes after ;
                    nv = cookie_part.split(";")[0].strip()
                    name, _, value = nv.partition("=")
                    if name:
                        self.cookies[name.strip()] = value.strip()
        self._parse_html()

    def _parse_html(self):
        soup = BeautifulSoup(self.html, "lxml")
        self.scripts = [
            tag["src"] for tag in soup.find_all("script", src=True)
        ]
        # Concatenate inline script contents (scripts without src)
        inline_parts = []
        for tag in soup.find_all("script"):
            if not tag.get("src") and tag.string:
                inline_parts.append(tag.string)
        self.inline_scripts = "\n".join(inline_parts)
        for tag in soup.find_all("meta"):
            name = tag.get("name") or tag.get("property") or ""
            content = tag.get("content") or ""
            if name:
                self.meta[name.lower()] = content

    @classmethod
    def new_from_url(cls, url: str, **kwargs) -> "WebPage":
        response = requests.get(url, timeout=10, **kwargs)
        return cls(url, response.text, dict(response.headers))
