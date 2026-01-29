"""edgar.py - SEC EDGAR integration for public company filings and financial data."""

import httpx
import re
from typing import Optional


# 8-K item codes that indicate meaningful trigger events
TRIGGER_ITEMS = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Failure to Satisfy Listing Rule",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
}

# Items that are high-signal for sales research
HIGH_SIGNAL_ITEMS = {"1.01", "1.02", "1.03", "2.01", "2.05", "2.06", "4.01", "4.02", "5.01", "5.02"}

# SEC requires this header on all requests
USER_AGENT = "AugmentedResearch admin@augmented.dev"


class EdgarService:
    """Service for fetching public company filings from SEC EDGAR."""

    def __init__(self):
        self._tickers_cache: Optional[dict] = None
        self._last_sic_code: Optional[str] = None  # Set after get_company_filings

    async def _load_tickers(self, client: httpx.AsyncClient) -> dict:
        """Load and cache the SEC company tickers JSON. Returns {name_lower: {cik, ticker, title}}."""
        if self._tickers_cache is not None:
            return self._tickers_cache

        response = await client.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        )
        if response.status_code != 200:
            self._tickers_cache = {}
            return self._tickers_cache

        data = response.json()
        # Build lookup by lowercase company name and by ticker
        lookup = {}
        for entry in data.values():
            name = entry["title"].lower().strip()
            ticker = entry["ticker"].upper().strip()
            record = {
                "cik": str(entry["cik_str"]).zfill(10),
                "ticker": ticker,
                "title": entry["title"],
            }
            lookup[name] = record
            lookup[ticker.lower()] = record

        self._tickers_cache = lookup
        return self._tickers_cache

    def _match_company(self, company_name: str, tickers: dict) -> Optional[dict]:
        """Try to match a company name to a SEC entity."""
        name = company_name.lower().strip()

        # Strip domain suffixes first (datadoghq.com -> datadoghq)
        for suffix in [".com", ".io", ".ai", ".co", ".org", ".net", ".dev", ".so", ".app"]:
            if name.endswith(suffix):
                name = name[:-len(suffix)].strip()
                break

        # Strip common domain name filler (datadoghq -> datadog)
        for filler in ["hq", "app", "inc", "corp", "global", "official"]:
            if name.endswith(filler) and len(name) > len(filler) + 2:
                candidate = name[:-len(filler)]
                # Check if stripped version matches before committing
                if candidate in tickers:
                    return tickers[candidate]
                # Also try with suffixes
                for s in [", inc.", " inc."]:
                    if (candidate + s) in tickers:
                        return tickers[candidate + s]

        # Direct match
        if name in tickers:
            return tickers[name]

        # Try common suffixes
        for suffix in [", inc.", ", inc", " inc.", " inc", ", corp.", ", corp", " corp.", " corp",
                       ", ltd.", ", ltd", " ltd.", " ltd", ", llc", " llc", ", co.", " co."]:
            if (name + suffix) in tickers:
                return tickers[name + suffix]

        # Try removing suffixes from the input
        for suffix in [", inc.", ", inc", " inc.", " inc",
                       ", corp.", " corp.", ", ltd.", " ltd.", ", llc", " llc"]:
            if name.endswith(suffix):
                stripped = name[:-len(suffix)].strip()
                if stripped in tickers:
                    return tickers[stripped]

        # Substring match — find SEC entries that contain our name (prefer shorter/closer matches)
        candidates = []
        for key, record in tickers.items():
            if len(key) < 3:
                continue
            # Check if our cleaned name appears at the start of an SEC title
            sec_title = record["title"].lower()
            if sec_title.startswith(name) or name == key:
                candidates.append((len(key), record))
        if candidates:
            # Return the shortest match (most specific)
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]

        return None

    async def get_company_filings(self, company_name: str) -> Optional[str]:
        """
        Fetch SEC EDGAR data for a public company.

        Returns formatted string for Claude prompt, or None if company is not public
        or lookup fails.
        """
        try:
            async with httpx.AsyncClient() as client:
                # Step 1: Resolve company name to CIK
                tickers = await self._load_tickers(client)
                match = self._match_company(company_name, tickers)
                if not match:
                    return None

                cik = match["cik"]
                ticker = match["ticker"]
                print(f"EDGAR: Found {match['title']} ({ticker}) — CIK {cik}")

                # Step 2: Get submissions (company metadata + all filings)
                submissions = await self._get_submissions(client, cik)
                if not submissions:
                    return None

                # Store SIC code for downstream use (e.g., Federal Register)
                self._last_sic_code = submissions.get("sic")

                # Step 3: Extract useful data
                sections = []
                sections.append(f"**Company:** {submissions.get('name', match['title'])} ({ticker})")
                sections.append(f"**SIC:** {submissions.get('sicDescription', 'Unknown')}")

                if submissions.get("stateOfIncorporation"):
                    sections.append(f"**Incorporated:** {submissions['stateOfIncorporation']}")
                if submissions.get("category"):
                    sections.append(f"**Filer Category:** {submissions['category']}")

                sections.append("")

                # Step 4: Extract recent 8-K trigger events
                eight_k_section = self._extract_8k_events(submissions)
                if eight_k_section:
                    sections.append(eight_k_section)

                # Step 5: Extract recent 10-K/10-Q filing info
                annual_section = self._extract_annual_filings(submissions)
                if annual_section:
                    sections.append(annual_section)

                # Step 6: Try to fetch Risk Factors from most recent 10-K
                risk_factors = await self._fetch_risk_factors(client, cik, submissions)
                if risk_factors:
                    sections.append("### Risk Factors (from 10-K)")
                    sections.append("(Company's own disclosure of business challenges and threats)")
                    sections.append(risk_factors)
                    sections.append("")

                return "\n".join(sections)

        except Exception as e:
            print(f"EDGAR error (non-fatal): {e}")
            return None

    async def _get_submissions(self, client: httpx.AsyncClient, cik: str) -> Optional[dict]:
        """Fetch the submissions JSON for a company."""
        response = await client.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        )
        if response.status_code != 200:
            print(f"EDGAR: Submissions request failed: {response.status_code}")
            return None
        return response.json()

    def _extract_8k_events(self, submissions: dict) -> Optional[str]:
        """Extract recent 8-K filings with trigger event descriptions."""
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        items_list = recent.get("items", [])
        descriptions = recent.get("primaryDocDescription", [])

        events = []
        for i, form in enumerate(forms):
            if form != "8-K" or i >= len(dates):
                continue

            filing_date = dates[i]
            items_str = items_list[i] if i < len(items_list) else ""
            item_codes = [c.strip() for c in items_str.split(",") if c.strip()]

            # Only include filings with meaningful items
            has_signal = any(code in HIGH_SIGNAL_ITEMS for code in item_codes)
            item_labels = []
            for code in item_codes:
                if code in TRIGGER_ITEMS:
                    item_labels.append(f"{code}: {TRIGGER_ITEMS[code]}")

            if item_labels:
                signal_marker = " ⚡" if has_signal else ""
                events.append(f"- **{filing_date}**{signal_marker}: {'; '.join(item_labels)}")

            if len(events) >= 10:
                break

        if not events:
            return None

        lines = ["### Recent 8-K Filings (Material Events)"]
        lines.extend(events)
        lines.append("")
        return "\n".join(lines)

    def _extract_annual_filings(self, submissions: dict) -> Optional[str]:
        """Extract recent 10-K and 10-Q filing dates."""
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])

        lines = []
        ten_k_count = 0
        ten_q_count = 0

        for i, form in enumerate(forms):
            if i >= len(dates):
                break
            filing_date = dates[i]
            report_date = report_dates[i] if i < len(report_dates) else ""

            if form == "10-K" and ten_k_count < 2:
                lines.append(f"- **10-K** (Annual Report): Filed {filing_date}, period ending {report_date}")
                ten_k_count += 1
            elif form == "10-Q" and ten_q_count < 3:
                lines.append(f"- **10-Q** (Quarterly Report): Filed {filing_date}, period ending {report_date}")
                ten_q_count += 1

            if ten_k_count >= 2 and ten_q_count >= 3:
                break

        if not lines:
            return None

        return "### Financial Filings\n" + "\n".join(lines) + "\n"

    async def _fetch_risk_factors(
        self, client: httpx.AsyncClient, cik: str, submissions: dict
    ) -> Optional[str]:
        """Fetch and extract the Risk Factors section from the most recent 10-K."""
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])

        # Find most recent 10-K
        for i, form in enumerate(forms):
            if form != "10-K":
                continue
            if i >= len(accession_numbers) or i >= len(primary_docs):
                break

            acc_no = accession_numbers[i].replace("-", "")
            doc = primary_docs[i]
            cik_int = cik.lstrip("0")

            url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no}/{doc}"

            try:
                response = await client.get(
                    url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=30.0,
                    follow_redirects=True,
                )
                if response.status_code != 200:
                    print(f"EDGAR: 10-K fetch failed: {response.status_code}")
                    return None

                return self._parse_risk_factors(response.text)
            except Exception as e:
                print(f"EDGAR: 10-K fetch error: {e}")
                return None

        return None

    def _parse_risk_factors(self, html: str) -> Optional[str]:
        """Extract the Risk Factors section from a 10-K HTML document."""
        # Remove HTML tags for text extraction
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&\w+;", " ", text)  # Remove HTML entities
        text = re.sub(r"\s+", " ", text)

        # Find ALL occurrences of "Item 1A" / "Risk Factors" — the first is usually
        # the table of contents, the second is the actual section
        pattern = r"Item\s+1A\.?\s*[-–—.]?\s*Risk\s+Factors"
        matches = list(re.finditer(pattern, text, re.IGNORECASE))

        if not matches:
            return None

        # Use the last match if there are multiple (skip TOC entries)
        # TOC entries are typically short; the real section is longer
        best_match = None
        for match in matches:
            remaining = text[match.end():]
            # Check if there's substantial content before next Item header
            next_item = re.search(r"Item\s+(?:1B|2)\b", remaining[:2000], re.IGNORECASE)
            content_length = next_item.start() if next_item else len(remaining[:2000])
            if content_length > 500:
                best_match = match
                break

        if best_match is None:
            # Fall back to last match
            best_match = matches[-1]

        start = best_match.end()
        remaining = text[start:]

        # Find the end — next Item header
        end_match = re.search(
            r"Item\s+(?:1B|2)\b",
            remaining,
            re.IGNORECASE,
        )

        if end_match:
            risk_text = remaining[:end_match.start()]
        else:
            risk_text = remaining[:8000]

        risk_text = risk_text.strip()
        if len(risk_text) > 6000:
            risk_text = risk_text[:6000] + "\n[... truncated for brevity]"

        if len(risk_text) < 200:
            return None

        return risk_text
