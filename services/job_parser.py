"""Parse job posting text for technology mentions and role signals."""

import re
from models import JobSignals, TechMention

TECH_KEYWORDS = {
    "language": [
        "Python", "Java", "JavaScript", "TypeScript", "Go", "Golang", "Rust", "Ruby",
        "C\\+\\+", "C#", "PHP", "Scala", "Kotlin", "Swift", "Objective-C", "R",
        "Perl", "Elixir", "Clojure", "Haskell", "Lua", "Dart",
    ],
    "framework": [
        "React", "Angular", "Vue", "Next\\.js", "Nuxt", "Django", "Flask", "FastAPI",
        "Spring", "Rails", "Express", "NestJS", "Laravel", "Svelte", "Remix",
        "ASP\\.NET", "Gin", "Echo", "Fiber", "Phoenix",
    ],
    "database": [
        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "DynamoDB",
        "Cassandra", "Neo4j", "SQLite", "MariaDB", "CockroachDB", "ClickHouse",
        "Snowflake", "BigQuery", "Redshift", "Supabase", "PlanetScale",
    ],
    "cloud": [
        "AWS", "Azure", "GCP", "Google Cloud", "Heroku", "Vercel", "Netlify",
        "DigitalOcean", "Cloudflare", "Fly\\.io",
    ],
    "data": [
        "Spark", "Kafka", "Airflow", "dbt", "Hadoop", "Flink", "Databricks",
        "Tableau", "Looker", "Power BI", "Segment", "Fivetran", "Snowplow",
    ],
    "devops": [
        "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins", "CircleCI",
        "GitHub Actions", "GitLab CI", "ArgoCD", "Helm", "Pulumi", "Datadog",
        "Prometheus", "Grafana", "New Relic", "PagerDuty", "Chronosphere",
        "Honeycomb", "Lightstep", "Dynatrace", "AppDynamics", "Elastic APM",
        "SignalFx", "Splunk", "OpenTelemetry", "Jaeger", "Zipkin",
        "ELK", "Kibana", "Logstash", "Fluentd", "Loki", "Tempo",
    ],
    "security": [
        "OAuth", "SAML", "SSO", "Vault", "Okta", "Auth0", "CrowdStrike",
        "SentinelOne", "Snyk", "SonarQube", "Splunk",
    ],
}

ROLE_PATTERNS = {
    # Technical roles
    "backend": r"\bback[\s-]?end\b",
    "frontend": r"\bfront[\s-]?end\b",
    "fullstack": r"\bfull[\s-]?stack\b",
    "data": r"\bdata\s+(engineer|scientist|analyst)\b",
    "devops": r"\b(devops|sre|site reliability|platform engineer)\b",
    "security": r"\b(security engineer|appsec|infosec|cybersecurity)\b",
    "mobile": r"\b(mobile|ios|android)\s+(engineer|developer)\b",
    # Business-function roles
    "marketing": r"\b(marketing\s+(manager|director|analyst|coordinator|specialist)|growth\s+marketing|content\s+strategist|seo\s+specialist|demand\s+gen(eration)?(\s+manager)?)\b",
    "sales": r"\b(sales\s+(manager|director|representative|engineer)|account\s+executive|revenue\s+operations|sdr|bdr)\b",
    "finance": r"\b(finance\s+(manager|director|analyst)|financial\s+analyst|controller|actuari(al|y)|underwriting(\s+manager)?)\b",
    "operations": r"\b(operations\s+(manager|director|analyst)|supply\s+chain(\s+manager)?|logistics(\s+manager)?|warehouse\s+manager|procurement(\s+manager)?)\b",
    "healthcare_clinical": r"\b(clinical\s+(director|manager|coordinator)|nursing(\s+director)?|physician|patient\s+care(\s+manager)?|care\s+coordinator)\b",
    "hr_people": r"\b(hr\s+(manager|director|generalist)|recruiter|talent\s+acquisition|people\s+operations)\b",
    "legal_compliance": r"\b(legal\s+counsel|compliance\s+(officer|manager|director)|contract\s+manager|regulatory\s+affairs)\b",
    "product": r"\b(product\s+(manager|director|owner)|product\s+designer|ux\s+designer)\b",
    "project_management": r"\bproject\s+manager\b",
    "construction": r"\b(estimator|superintendent|safety\s+manager|field\s+operations(\s+manager)?)\b",
    "education": r"\b(curriculum\s+designer|instructional\s+design(er)?|teacher|instructor)\b",
}

SENIORITY_PATTERNS = {
    "junior": r"\b(junior|jr\.?|entry[\s-]level)\b",
    "mid": r"\b(mid[\s-]level|intermediate)\b",
    "senior": r"\bsenior\b",
    "staff": r"\bstaff\b",
    "principal": r"\bprincipal\b",
    "lead": r"\b(lead|tech lead|team lead)\b",
    "manager": r"\b(manager|engineering manager)\b",
    "director": r"\bdirector\b",
}

INITIATIVE_PATTERNS = {
    "Cloud migration / modernization": [
        r"\bcloud migration\b",
        r"\bmigrate (?:to|into) (?:aws|azure|gcp|google cloud)\b",
        r"\bmoderniz(?:e|ation|ing)\b",
        r"\blegacy (?:system|application|platform)\b",
        r"\blanding zone\b",
        r"\bwell-architected\b",
        r"\bfinops\b",
        r"\bmulti-account\b",
    ],
    "Platform engineering buildout": [
        r"\bplatform engineering\b",
        r"\bplatform team\b",
        r"\bdeveloper platform\b",
        r"\binternal developer platform\b",
        r"\bshared platform\b",
        r"\bplatform modernization\b",
    ],
    "Data platform / analytics buildout": [
        r"\bdata platform\b",
        r"\bdata warehouse\b",
        r"\bdata lake(?:house)?\b",
        r"\banalytics platform\b",
        r"\bmodern data stack\b",
        r"\breporting platform\b",
        r"\bbusiness intelligence\b",
    ],
    "AI / ML rollout": [
        r"\bgenerative ai\b",
        r"\bgenai\b",
        r"\bllm\b",
        r"\bmachine learning\b",
        r"\bmlops\b",
        r"\bai product\b",
        r"\bai initiative\b",
        r"\bai/ml\b",
    ],
    "Security / compliance program": [
        r"\bzero trust\b",
        r"\bidentity and access management\b",
        r"\biam\b",
        r"\bsoc ?2\b",
        r"\biso ?27001\b",
        r"\bfedramp\b",
        r"\bpci\b",
        r"\bcompliance program\b",
        r"\bsecurity transformation\b",
    ],
    "Quality engineering / test automation": [
        r"\bqa automation\b",
        r"\btest automation\b",
        r"\bquality engineering\b",
        r"\bautomated testing\b",
        r"\btest platform\b",
    ],
}

DELIVERY_MODEL_PATTERNS = {
    "Professional services / consulting language": [
        r"\bprofessional services\b",
        r"\bconsult(?:ant|ing)\b",
        r"\bimplementation partner\b",
        r"\bservices partner\b",
        r"\bsystems integrator\b",
        r"\bmanaged service(?:s)?\b",
    ],
    "Partner / vendor coordination": [
        r"\bexternal partner\b",
        r"\bthird-?party vendor\b",
        r"\bvendor management\b",
        r"\bvendor relationships?\b",
        r"\bpartner management\b",
        r"\bmanage (?:strategic )?partners\b",
        r"\bcoordinate with vendors\b",
    ],
    "Contractor / external team usage": [
        r"\bcontractor\b",
        r"\boutsourc(?:e|ed|ing)\b",
        r"\baugmented team\b",
        r"\bexternal team\b",
        r"\bconsulting resources\b",
    ],
}

_INITIATIVE_EXPECTED_ROLES = {
    "Cloud migration / modernization": {"devops", "backend", "fullstack", "security"},
    "Platform engineering buildout": {"devops", "backend", "fullstack", "product"},
    "Data platform / analytics buildout": {"data", "backend", "fullstack"},
    "AI / ML rollout": {"data", "backend", "fullstack", "devops"},
    "Security / compliance program": {"security", "devops", "legal_compliance"},
    "Quality engineering / test automation": {"backend", "fullstack", "devops", "product"},
}

_INITIATIVE_GAP_LABELS = {
    "Cloud migration / modernization": "DevOps/platform",
    "Platform engineering buildout": "platform/DevOps",
    "Data platform / analytics buildout": "data engineering/analytics",
    "AI / ML rollout": "AI/ML platform",
    "Security / compliance program": "security/compliance",
    "Quality engineering / test automation": "QA/automation",
}

_SPECIALIST_ROLE_TYPES = {
    "backend", "frontend", "fullstack", "data", "devops", "security",
    "mobile", "product", "project_management",
}


class JobParser:
    """Parse job posting text for technology and role signals."""

    def parse(self, job_text: str) -> JobSignals:
        if not job_text:
            return JobSignals()

        text_lower = job_text.lower()

        # Tech mentions
        tech_mentions = []
        for category, keywords in TECH_KEYWORDS.items():
            for kw in keywords:
                matches = re.findall(rf"\b{kw}\b", job_text, re.IGNORECASE)
                if matches:
                    # Use the first match's original casing for display name
                    display_name = re.sub(r"\\", "", kw)  # Clean escaped chars
                    tech_mentions.append(TechMention(
                        name=display_name,
                        category=category,
                        count=len(matches),
                    ))

        # Role types
        role_type_counts: dict[str, int] = {}
        role_types = []
        for role, pattern in ROLE_PATTERNS.items():
            count = len(re.findall(pattern, text_lower))
            if count:
                role_types.append(role)
                role_type_counts[role] = count

        # Seniority
        seniority: dict[str, int] = {}
        for level, pattern in SENIORITY_PATTERNS.items():
            count = len(re.findall(pattern, text_lower))
            if count:
                seniority[level] = count

        initiative_signals = self._extract_label_signals(job_text, INITIATIVE_PATTERNS)
        delivery_model_signals = self._extract_label_signals(job_text, DELIVERY_MODEL_PATTERNS)
        capacity_signals = self._derive_capacity_signals(role_type_counts, seniority, initiative_signals)
        capability_gap_signals = self._derive_capability_gap_signals(
            role_type_counts,
            seniority,
            initiative_signals,
        )

        # Rough role count: count lines starting with common role title patterns
        role_lines = re.findall(
            r"(?:^|\n)\s*(?:senior|junior|staff|lead|principal)?\s*\w+\s+"
            r"(?:engineer|manager|director|analyst|specialist|coordinator|designer|recruiter|counsel)",
            text_lower,
        )
        total = max(len(role_lines), 1) if (tech_mentions or role_types) else 0

        return JobSignals(
            tech_mentions=tech_mentions,
            role_types=role_types,
            role_type_counts=role_type_counts,
            seniority_distribution=seniority,
            initiative_signals=initiative_signals,
            delivery_model_signals=delivery_model_signals,
            capacity_signals=capacity_signals,
            capability_gap_signals=capability_gap_signals,
            total_roles_parsed=total,
        )

    @staticmethod
    def _extract_label_signals(text: str, pattern_map: dict[str, list[str]]) -> list[str]:
        """Return signal labels whose regex patterns match the job text."""
        signals: list[str] = []
        for label, patterns in pattern_map.items():
            if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
                signals.append(label)
        return signals

    @staticmethod
    def _derive_capacity_signals(
        role_type_counts: dict[str, int],
        seniority: dict[str, int],
        initiative_signals: list[str],
    ) -> list[str]:
        """Summarize notable hiring-shape patterns that imply active delivery pressure."""
        signals: list[str] = []
        specialist_counts = {role: count for role, count in role_type_counts.items() if role in _SPECIALIST_ROLE_TYPES}
        total_specialists = sum(specialist_counts.values())

        if total_specialists >= 3 and len(specialist_counts) >= 2:
            ordered_roles = sorted(specialist_counts, key=lambda role: (-specialist_counts[role], role))
            signals.append(f"Coordinated specialist hiring across {', '.join(ordered_roles)}")

        leadership_count = seniority.get("manager", 0) + seniority.get("director", 0)
        senior_count = seniority.get("senior", 0) + seniority.get("staff", 0) + seniority.get("principal", 0)
        junior_count = seniority.get("junior", 0) + seniority.get("mid", 0)

        if leadership_count >= 1 and initiative_signals and total_specialists <= 2:
            signals.append("Leadership-first hiring mix for an active initiative")

        if senior_count >= 3 and junior_count == 0 and total_specialists >= 2:
            signals.append("Senior-heavy specialist hiring mix")

        return signals

    @staticmethod
    def _derive_capability_gap_signals(
        role_type_counts: dict[str, int],
        seniority: dict[str, int],
        initiative_signals: list[str],
    ) -> list[str]:
        """Call out likely initiative/capacity mismatches useful for services sellers."""
        gaps: list[str] = []
        leadership_count = seniority.get("manager", 0) + seniority.get("director", 0)
        total_specialists = sum(
            count for role, count in role_type_counts.items() if role in _SPECIALIST_ROLE_TYPES
        )

        for initiative in initiative_signals:
            expected_roles = _INITIATIVE_EXPECTED_ROLES.get(initiative, set())
            matched_roles = [role for role in expected_roles if role_type_counts.get(role, 0) > 0]
            if not matched_roles:
                role_label = _INITIATIVE_GAP_LABELS.get(initiative, "specialist")
                gaps.append(f"{initiative} language without dedicated {role_label} hiring")

        if leadership_count >= 1 and initiative_signals and total_specialists <= 2:
            gaps.append("Manager/director hiring appears ahead of execution-team buildout")

        return list(dict.fromkeys(gaps))
