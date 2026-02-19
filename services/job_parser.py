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
        role_types = []
        for role, pattern in ROLE_PATTERNS.items():
            if re.search(pattern, text_lower):
                role_types.append(role)

        # Seniority
        seniority: dict[str, int] = {}
        for level, pattern in SENIORITY_PATTERNS.items():
            count = len(re.findall(pattern, text_lower))
            if count:
                seniority[level] = count

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
            seniority_distribution=seniority,
            total_roles_parsed=total,
        )
