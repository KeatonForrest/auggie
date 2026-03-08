"""Pain inference engine — derive actionable pain signals from collected data."""

import logging
from typing import Optional
from models import SignalBundle, PainInference, TechStack, SellerContext
from config import get_settings

logger = logging.getLogger(__name__)

# ── Category policy: deterministic Action Tier relevance gate ──

_CATEGORY_KEYWORDS = {
    "database": [
        "database", "db ", "data warehouse", "data lake", "sql", "nosql",
        "mongodb", "postgres", "postgresql", "mysql", "redis", "dynamodb",
        "cassandra", "cockroachdb", "data platform", "data infrastructure",
        "vector database", "graph database", "time-series", "olap", "oltp",
    ],
    "fintech": [
        "payments", "banking", "lending", "kyc", "aml", "billing platform",
        "payment processing", "financial services", "neobank", "fintech",
        "transaction", "pci", "card issuing", "underwriting", "regtech",
    ],
    "healthtech": [
        "healthcare", "ehr", "telehealth", "hipaa", "clinical", "patient",
        "health tech", "healthtech", "medical device", "digital health",
        "electronic health record", "health information", "care coordination",
    ],
    "martech": [
        "marketing automation", "cdp", "attribution", "personalization",
        "customer data platform", "campaign management", "martech",
        "marketing platform", "email marketing", "lead scoring",
        "marketing analytics", "demand generation",
    ],
    "devtools": [
        "developer tools", "ci/cd", "observability", "apm", "kubernetes",
        "devtools", "developer experience", "build system", "deployment",
        "infrastructure as code", "monitoring", "logging", "container",
        "developer platform",
    ],
    "security": [
        "cybersecurity", "security", "siem", "soar", "zero trust", "identity",
        "access management", "threat detection", "vulnerability", "penetration",
        "endpoint protection", "soc ", "security operations", "encryption",
    ],
    "hrtech": [
        "hris", "human resources", "payroll", "talent management", "recruiting",
        "applicant tracking", "workforce", "employee engagement", "hr tech",
        "people analytics", "benefits administration", "onboarding platform",
    ],
    "legaltech": [
        "legal tech", "contract management", "clm", "ediscovery", "legal ops",
        "compliance management", "legal automation", "case management",
        "document review", "legal workflow",
    ],
    "ecommerce": [
        "ecommerce", "e-commerce", "shopping cart", "checkout", "product catalog",
        "order management", "inventory management", "marketplace", "storefront",
        "commerce platform", "fulfillment", "dropship",
    ],
    "constructiontech": [
        "construction", "building information", "bim", "project management",
        "field service", "jobsite", "subcontractor", "estimating",
        "construction management", "blueprints", "takeoff",
    ],
    "edtech": [
        "education", "lms", "learning management", "edtech", "courseware",
        "student", "curriculum", "e-learning", "training platform",
        "instructional design", "classroom",
    ],
    "proptech": [
        "real estate", "property management", "proptech", "lease", "tenant",
        "building management", "smart building", "real estate technology",
        "mls", "property listing",
    ],
    "insurtech": [
        "insurance", "insurtech", "underwriting", "claims management",
        "actuarial", "policy management", "insurance platform",
        "risk assessment", "insurance automation",
    ],
    "supplychain": [
        "supply chain", "logistics", "freight", "warehouse management",
        "transportation management", "fleet", "last mile", "procurement",
        "supply chain visibility", "inventory optimization",
    ],
    "govtech": [
        "government", "govtech", "civic tech", "public sector", "fedramp",
        "government contracting", "municipal", "citizen services",
        "government procurement", "public safety",
    ],
}

_FRONTEND_DENYLIST = {
    "frontend_frameworks", "cdn_delivery", "css_tooling", "marketing_tags",
}

# Per-category linkage terms (override blocked signals when present)
_CATEGORY_LINKAGE_TERMS: dict[str, list[str]] = {
    "database": [
        "database bottleneck", "db bottleneck", "query performance",
        "api latency", "data pipeline", "backend performance",
        "read replica", "write throughput", "connection pool",
        "slow queries", "index", "migration", "data-intensive",
    ],
    "fintech": [
        "payment flow", "transaction", "pci", "financial data",
        "billing integration", "payment processing", "ledger",
    ],
    "healthtech": [
        "patient data", "ehr integration", "clinical workflow", "hipaa",
        "health record", "care coordination", "telehealth",
    ],
    "martech": [
        "customer data", "campaign performance", "lead scoring",
        "marketing analytics", "attribution", "conversion",
    ],
    "devtools": [
        "developer experience", "build time", "pipeline",
        "infrastructure", "deployment velocity", "developer productivity",
    ],
}

# Backward compat alias
_DB_LINKAGE_TERMS = _CATEGORY_LINKAGE_TERMS["database"]

# Maps rule_id → set of signal families the rule belongs to
_RULE_FAMILIES: dict[str, set[str]] = {
    "frontend_performance_debt": {"frontend_frameworks"},
    "tag_bloat": {"marketing_tags"},
    "marketing_product_mismatch": {"frontend_frameworks"},
}

# Maps seller category → set of denied signal families
_CATEGORY_DENYLISTS: dict[str, set[str]] = {
    "database": _FRONTEND_DENYLIST,
    "fintech": {"frontend_frameworks", "cdn_delivery", "marketing_tags"},
    "healthtech": {"frontend_frameworks", "cdn_delivery", "marketing_tags"},
    "martech": {"devops_infra", "security_scanning"},
    "devtools": {"marketing_tags", "crm_sales"},
}


def detect_seller_category(product_context: str) -> str:
    """Detect seller product category from product context using keyword hits.

    Returns the category with >= 2 keyword hits, or "" if none match.
    """
    if not product_context:
        return ""
    text = product_context.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits >= 2:
            return category
    return ""


def is_action_tier_relevant(inference: PainInference, seller_category: str) -> bool:
    """Determine if a pain inference is relevant for Action Tier fields.

    Returns True if the signal should be included in Action Tier
    (existential_data_points, pvp_seed, talking_points). Returns False
    if the signal should be suppressed from Action Tier (kept for
    background context only).
    """
    if not seller_category or seller_category not in _CATEGORY_DENYLISTS:
        return True
    denied_families = _CATEGORY_DENYLISTS[seller_category]
    rule_families = _RULE_FAMILIES.get(inference.rule_id, set())
    if not rule_families.intersection(denied_families):
        return True
    # Check for linkage override: evidence text contains category-specific terms
    linkage_terms = _CATEGORY_LINKAGE_TERMS.get(seller_category, [])
    if linkage_terms:
        evidence_text = " ".join(inference.evidence).lower()
        description_text = inference.description.lower()
        combined = evidence_text + " " + description_text
        if any(term in combined for term in linkage_terms):
            return True
    return False


class PainInferenceEngine:
    """Evaluate a SignalBundle and return scored pain inferences."""

    # Meta-framework pairs: if only these two are detected, don't fire frontend_performance_debt
    META_FRAMEWORK_PAIRS = {
        frozenset({"Next.js", "React"}),
        frozenset({"Nuxt.js", "Vue.js"}),
        frozenset({"Nuxt", "Vue"}),
        frozenset({"Next.js", "React.js"}),
        frozenset({"SvelteKit", "Svelte"}),
    }

    APM_NAMES = {
        "datadog", "new relic", "sentry", "pagerduty", "grafana", "prometheus",
        "splunk", "dynatrace", "appdynamics", "honeycomb", "lightstep", "elastic apm",
        "chronosphere", "signalfx", "opentelemetry", "jaeger", "zipkin",
        "elk", "kibana", "logstash", "fluentd", "loki", "tempo",
    }

    DATABASE_NAMES = {
        "postgresql", "mysql", "mongodb", "mariadb", "cockroachdb", "sqlite",
        "dynamodb", "cassandra",
    }

    CACHE_NAMES = {"redis", "memcached", "varnish", "hazelcast"}

    CATEGORY_KEYWORDS: dict[str, list[str]] = {
        "security": ["security", "compliance", "soc2", "gdpr", "vulnerability", "firewall", "identity", "auth", "zero trust", "siem", "threat", "encryption", "pentest"],
        "engineering": ["developer", "engineering", "devops", "ci/cd", "deployment", "code", "api", "platform", "infrastructure", "scaling", "performance", "database", "backend", "frontend", "sdk"],
        "operations": ["operations", "cloud", "monitoring", "observability", "itsm", "helpdesk", "ticketing", "asset", "network", "incident", "uptime"],
        "marketing": ["marketing", "analytics", "cdp", "attribution", "tracking", "advertising", "seo", "crm", "customer data", "personalization", "campaign"],
        "data": ["data", "warehouse", "etl", "pipeline", "bi", "machine learning", "ml", "lakehouse", "dbt", "snowflake", "databricks", "ai"],
    }

    AUTH_PROVIDER_NAMES = {
        "auth0", "okta", "firebase auth", "cognito", "clerk", "onelogin",
        "ping identity", "azure ad", "keycloak",
    }

    def evaluate(self, bundle: SignalBundle, seller: Optional[SellerContext] = None,
                 seller_product_context: str = "") -> list[PainInference]:
        settings = get_settings()

        rules = [
            self._identity_fragmentation,
            self._tech_debt,
            self._security_gap,
            self._scaling_pressure,
            self._multi_cloud,
            self._cert_gap,
            self._marketing_product_mismatch,
            self._data_infra_pain,
            self._tag_bloat,
            self._vendor_lock_in,
            self._compliance_gap,
            self._hiring_velocity_anomaly,
            self._tool_sprawl,
            self._observability_gap,
            self._database_scaling_pressure,
            self._auth_fragmentation,
        ]

        # Gate: frontend_performance_debt only runs when flag is on
        if getattr(settings, "pain_frontend_rule_enabled", False):
            rules.append(self._frontend_performance_debt)
        else:
            logger.debug("pain_frontend_rule_enabled=off, skipping frontend_performance_debt")

        results = []
        for rule in rules:
            inference = rule(bundle)
            if inference:
                results.append(inference)
        self._evaluate_compounds(results)
        self._apply_dampeners(results, bundle)
        self._apply_detection_confidence(results, bundle)
        # Detect seller category for weighting and action tier gating
        seller_category = detect_seller_category(seller_product_context)

        if seller is not None:
            self._apply_seller_weighting(results, seller, seller_category=seller_category)
            results = [r for r in results if r.confidence > 0]
        if seller_category:
            filtered_count = 0
            for r in results:
                if not is_action_tier_relevant(r, seller_category):
                    r.category = f"_background_{r.category}"
                    filtered_count += 1
            if filtered_count:
                logger.info("pain_signal_filtered_irrelevant: %d signals demoted to background for %s seller",
                            filtered_count, seller_category)

        results.sort(key=lambda x: x.confidence, reverse=True)
        return results

    def _get_all_tech_names_and_cats(self, bundle: SignalBundle) -> list[tuple[str, str]]:
        """Return (name, category) pairs from all tech detections."""
        pairs = []
        for domain, stack in bundle.tech_by_domain.items():
            if isinstance(stack, TechStack):
                for t in stack.technologies:
                    pairs.append((t.name, (t.category or "").lower()))
            elif isinstance(stack, dict):
                for t in stack.get("technologies", []):
                    pairs.append((t.get("name", ""), (t.get("category", "") or "").lower()))
        return pairs

    def _get_tech_names_by_domain(self, bundle: SignalBundle) -> dict[str, list[str]]:
        """Return {domain: [tech_name, ...]} mapping."""
        result = {}
        for domain, stack in bundle.tech_by_domain.items():
            names = []
            if isinstance(stack, TechStack):
                names = [t.name for t in stack.technologies]
            elif isinstance(stack, dict):
                names = [t.get("name", "") for t in stack.get("technologies", [])]
            result[domain] = names
        return result

    def _identity_fragmentation(self, bundle: SignalBundle) -> Optional[PainInference]:
        techs = self._get_all_tech_names_and_cats(bundle)
        analytics = [n for n, c in techs if "analytics" in c or "tag manager" in c or "advertising" in c]
        cdps = [n for n, c in techs if "cdp" in c or "customer data" in c.lower()]
        if len(analytics) >= 3 and not cdps:
            return PainInference(
                rule_id="identity_fragmentation",
                title="Identity Fragmentation",
                description="Multiple analytics/tracking tools detected without a CDP, suggesting fragmented customer identity.",
                severity="high",
                evidence=[f"Detected {len(analytics)} analytics/tracking tools: {', '.join(analytics[:5])}", "No CDP detected"],
                confidence=75,
                category="marketing",
            )
        return None

    def _tech_debt(self, bundle: SignalBundle) -> Optional[PainInference]:
        techs = self._get_all_tech_names_and_cats(bundle)
        names_lower = {n.lower() for n, _ in techs}
        eol = []
        if "angularjs" in names_lower:
            eol.append("AngularJS")
        if "jquery ui" in names_lower:
            eol.append("jQuery UI")
        for domain, stack in bundle.tech_by_domain.items():
            if isinstance(stack, TechStack):
                for t in stack.technologies:
                    if t.name.lower() == "php" and t.version:
                        try:
                            major = int(t.version.split(".")[0])
                            if major < 8:
                                eol.append(f"PHP {t.version}")
                        except (ValueError, IndexError):
                            pass
        modern = any(n.lower() in ("react", "vue", "angular", "svelte", "next.js") for n, _ in techs)
        if eol and modern:
            return PainInference(
                rule_id="tech_debt",
                title="Tech Debt Tension",
                description="End-of-life technology coexists with modern frontend, indicating migration pressure.",
                severity="medium",
                evidence=[f"EOL tech: {', '.join(eol)}", "Modern frontend also detected"],
                confidence=65,
                category="engineering",
            )
        return None

    def _security_gap(self, bundle: SignalBundle) -> Optional[PainInference]:
        infra = bundle.infra
        if infra and infra.security_score <= 2:
            evidence = [f"Security header score: {infra.security_score}/6 (grade {infra.security_grade})", f"Missing headers: {', '.join(infra.security_missing[:3])}"]
            return PainInference(
                rule_id="security_gap",
                title="Security Posture Gap",
                description="Weak security headers signal broad security underinvestment.",
                severity="high",
                evidence=evidence,
                confidence=75,
                category="security",
            )
        return None

    def _scaling_pressure(self, bundle: SignalBundle) -> Optional[PainInference]:
        js = bundle.job_signals
        if not js:
            return None
        devops_roles = [r for r in js.role_types if r in ("devops", "security")]
        cloud_hints = bundle.infra.cloud_provider_hints if bundle.infra else []
        if devops_roles and len(set(cloud_hints)) <= 1:
            return PainInference(
                rule_id="scaling_pressure",
                title="Scaling Pressure",
                description="DevOps/SRE hiring signals combined with single cloud provider suggest scaling challenges.",
                severity="medium",
                evidence=[f"DevOps-related roles detected: {', '.join(devops_roles)}", f"Cloud hints: {', '.join(cloud_hints) or 'single/unknown'}"],
                confidence=55,
                category="engineering",
            )
        return None

    def _multi_cloud(self, bundle: SignalBundle) -> Optional[PainInference]:
        clouds = set()
        if bundle.infra:
            clouds.update(bundle.infra.cloud_provider_hints)
        techs = self._get_all_tech_names_and_cats(bundle)
        for n, c in techs:
            nl = n.lower()
            if "aws" in nl or "amazon" in nl:
                clouds.add("AWS")
            elif "azure" in nl:
                clouds.add("Azure")
            elif "gcp" in nl or "google cloud" in nl:
                clouds.add("GCP")
        if len(clouds) >= 2:
            return PainInference(
                rule_id="multi_cloud",
                title="Multi-Cloud Complexity",
                description="Multiple cloud providers detected, indicating potential complexity and cost management challenges.",
                severity="medium",
                evidence=[f"Cloud providers: {', '.join(sorted(clouds))}"],
                confidence=60,
                category="operations",
            )
        return None

    def _email_risk(self, bundle: SignalBundle) -> Optional[PainInference]:
        infra = bundle.infra
        if not infra:
            return None
        issues = []
        if not infra.has_spf:
            issues.append("Missing SPF record")
        if not infra.has_dkim:
            issues.append("Missing DKIM record")
        if infra.has_dmarc and infra.dmarc_policy == "none":
            issues.append("DMARC policy set to 'none' (monitoring only)")
        elif not infra.has_dmarc:
            issues.append("No DMARC record")
        if issues:
            return PainInference(
                rule_id="email_risk",
                title="Email Authentication Risk",
                description="Email authentication gaps increase phishing/spoofing risk.",
                severity="medium",
                evidence=issues,
                confidence=70,
                category="security",
            )
        return None

    def _cert_gap(self, bundle: SignalBundle) -> Optional[PainInference]:
        infra = bundle.infra
        if not infra or infra.ssl_expiry_days is None:
            return None
        if infra.ssl_expiry_days < 30 and not infra.ssl_automation_inferred:
            return PainInference(
                rule_id="cert_gap",
                title="Certificate Expiry Risk",
                description="SSL certificate expiring soon without automated renewal detected.",
                severity="high",
                evidence=[f"Certificate expires in {infra.ssl_expiry_days} days", f"Issuer: {infra.ssl_issuer or 'unknown'}", "No automation (e.g. Let's Encrypt) detected"],
                confidence=85,
                category="security",
            )
        return None

    def _marketing_product_mismatch(self, bundle: SignalBundle) -> Optional[PainInference]:
        app_frameworks = set()
        main_frameworks = set()
        app_prefixes = ("app.", "dashboard.", "portal.", "console.", "platform.", "my.", "admin.", "web.")
        for domain, stack in bundle.tech_by_domain.items():
            techs = []
            if isinstance(stack, TechStack):
                techs = [(t.name, (t.category or "").lower()) for t in stack.technologies]
            elif isinstance(stack, dict):
                techs = [(t.get("name", ""), (t.get("category", "") or "").lower()) for t in stack.get("technologies", [])]
            frameworks = {n for n, c in techs if "framework" in c or "javascript" in c}
            if domain.startswith(app_prefixes):
                app_frameworks.update(frameworks)
            else:
                main_frameworks.update(frameworks)
        if app_frameworks and main_frameworks and not app_frameworks.intersection(main_frameworks):
            return PainInference(
                rule_id="marketing_product_mismatch",
                title="Marketing/Product Tech Mismatch",
                description="Different frameworks on marketing site vs product app, suggesting separate teams or tech debt.",
                severity="low",
                evidence=[f"Product frameworks: {', '.join(sorted(app_frameworks))}", f"Marketing frameworks: {', '.join(sorted(main_frameworks))}"],
                confidence=45,
                category="marketing",
            )
        return None

    def _data_infra_pain(self, bundle: SignalBundle) -> Optional[PainInference]:
        js = bundle.job_signals
        if not js:
            return None
        data_roles = [r for r in js.role_types if r == "data"]
        if len(data_roles) >= 1:
            return PainInference(
                rule_id="data_infra_pain",
                title="Data Infrastructure Growth Pain",
                description="Multiple data-related roles signal growing data infrastructure needs.",
                severity="medium",
                evidence=[f"Data role types: {', '.join(js.role_types)}", f"Total roles parsed: {js.total_roles_parsed}"],
                confidence=50,
                category="data",
            )
        return None

    def _tag_bloat(self, bundle: SignalBundle) -> Optional[PainInference]:
        techs = self._get_all_tech_names_and_cats(bundle)
        tag_techs = [n for n, c in techs if any(k in c for k in ("analytics", "advertising", "tag manager"))]
        if len(tag_techs) >= 6:
            return PainInference(
                rule_id="tag_bloat",
                title="Tag/Analytics Bloat",
                description="High number of analytics/advertising/tag-manager tools detected, indicating potential performance and governance issues.",
                severity="medium",
                evidence=[f"Detected {len(tag_techs)} analytics/ad/tag tools: {', '.join(tag_techs[:8])}"],
                confidence=60,
                category="marketing",
            )
        return None

    def _vendor_lock_in(self, bundle: SignalBundle) -> Optional[PainInference]:
        vendor_sources: dict[str, set[str]] = {}
        infra = bundle.infra
        if infra:
            for vendor, keywords in [("AWS", ["aws", "amazon"]), ("Azure", ["azure", "microsoft"]), ("GCP", ["gcp", "google"])]:
                if infra.ns_provider and any(k in infra.ns_provider.lower() for k in keywords):
                    vendor_sources.setdefault(vendor, set()).add("DNS NS")
                if infra.mx_provider and any(k in infra.mx_provider.lower() for k in keywords):
                    vendor_sources.setdefault(vendor, set()).add("Email")
        techs = self._get_all_tech_names_and_cats(bundle)
        for n, c in techs:
            nl = n.lower()
            for vendor, keywords in [("AWS", ["aws", "amazon"]), ("Azure", ["azure"]), ("GCP", ["gcp", "google cloud"])]:
                if any(k in nl for k in keywords):
                    if "cdn" in c:
                        vendor_sources.setdefault(vendor, set()).add("CDN")
                    else:
                        vendor_sources.setdefault(vendor, set()).add("Tech stack")
        for vendor, sources in vendor_sources.items():
            if len(sources) >= 3:
                return PainInference(
                    rule_id="vendor_lock_in",
                    title="Vendor Lock-In Risk",
                    description=f"Single cloud vendor ({vendor}) appears across multiple signal sources, suggesting deep lock-in.",
                    severity="medium",
                    evidence=[f"{vendor} detected in: {', '.join(sorted(sources))}"],
                    confidence=55,
                    category="operations",
                )
        return None

    def _compliance_gap(self, bundle: SignalBundle) -> Optional[PainInference]:
        infra = bundle.infra
        js = bundle.job_signals
        if not infra or infra.security_score > 2:
            return None
        if not js:
            return None
        has_security_signal = "security" in js.role_types
        if not has_security_signal:
            security_keywords = {"hipaa", "soc2", "soc 2", "pci", "gdpr", "compliance", "fedramp"}
            for tm in js.tech_mentions:
                if tm.name.lower() in security_keywords or tm.category == "security":
                    has_security_signal = True
                    break
        if not has_security_signal:
            return None
        evidence = [f"Security header grade: {infra.security_grade} ({infra.security_score}/6)"]
        evidence.append("Security-related hiring signals detected")
        return PainInference(
            rule_id="compliance_gap",
            title="Compliance Gap",
            description="Weak security posture combined with security hiring signals suggests compliance exposure.",
            severity="high",
            evidence=evidence,
            confidence=70,
            category="security",
        )

    def _frontend_performance_debt(self, bundle: SignalBundle) -> Optional[PainInference]:
        techs = self._get_all_tech_names_and_cats(bundle)
        frameworks = set()
        has_cdn = False
        for n, c in techs:
            if "framework" in c or "javascript" in c:
                frameworks.add(n)
            if "cdn" in c:
                has_cdn = True
        if len(frameworks) >= 2 and not has_cdn:
            # Dampener: skip if only 2 frameworks and one is a meta-framework wrapping the other
            if len(frameworks) == 2 and frozenset(frameworks) in self.META_FRAMEWORK_PAIRS:
                return None
            return PainInference(
                rule_id="frontend_performance_debt",
                title="Frontend Performance Debt",
                description="Multiple JS frameworks without a CDN suggests frontend performance and bundle size issues.",
                severity="medium",
                evidence=[f"Frameworks: {', '.join(sorted(frameworks))}", "No CDN detected"],
                confidence=50,
                category="engineering",
            )
        return None

    def _hiring_velocity_anomaly(self, bundle: SignalBundle) -> Optional[PainInference]:
        js = bundle.job_signals
        if not js or not js.seniority_distribution:
            return None
        senior_keys = {"senior", "staff", "principal"}
        junior_keys = {"junior", "mid"}
        senior_count = sum(v for k, v in js.seniority_distribution.items() if k in senior_keys)
        junior_count = sum(v for k, v in js.seniority_distribution.items() if k in junior_keys)
        if senior_count >= 3 and junior_count == 0:
            return PainInference(
                rule_id="hiring_velocity_anomaly",
                title="Execution Bottleneck",
                description="Heavily top-heavy hiring (senior/staff/principal with no junior/mid) suggests execution bottleneck or overly complex problems.",
                severity="medium",
                evidence=[f"Senior+Staff+Principal: {senior_count}", f"Junior+Mid: {junior_count}",
                          f"Distribution: {js.seniority_distribution}"],
                confidence=50,
                category="engineering",
            )
        if junior_count >= 3 and senior_count == 0:
            return PainInference(
                rule_id="hiring_velocity_anomaly",
                title="Leadership Gap",
                description="Heavily bottom-heavy hiring (junior/mid with no senior/staff) suggests leadership gap or inability to attract senior talent.",
                severity="medium",
                evidence=[f"Junior+Mid: {junior_count}", f"Senior+Staff+Principal: {senior_count}",
                          f"Distribution: {js.seniority_distribution}"],
                confidence=50,
                category="engineering",
            )
        return None

    def _tool_sprawl(self, bundle: SignalBundle) -> Optional[PainInference]:
        techs = self._get_all_tech_names_and_cats(bundle)
        unique_names = {n for n, _ in techs}
        if len(unique_names) >= 40:
            from collections import Counter
            cat_counts = Counter(c for _, c in techs if c)
            top_cats = cat_counts.most_common(5)
            return PainInference(
                rule_id="tool_sprawl",
                title="Tool Sprawl",
                description="Excessive number of distinct technologies detected, suggesting tool sprawl and governance challenges.",
                severity="medium",
                evidence=[f"Total unique technologies: {len(unique_names)}",
                          f"Top categories: {', '.join(f'{cat} ({cnt})' for cat, cnt in top_cats)}"],
                confidence=55,
                category="operations",
            )
        return None

    def _observability_gap(self, bundle: SignalBundle) -> Optional[PainInference]:
        app_prefixes = ("app.", "dashboard.", "portal.", "console.", "platform.", "my.", "admin.", "web.")
        product_subdomains = [d for d in bundle.tech_by_domain if d.startswith(app_prefixes)]
        if not product_subdomains:
            return None

        # Collect specific APM/observability tools from tech detection
        found_tools: set[str] = set()
        all_names_lower = {n.lower() for n, _ in self._get_all_tech_names_and_cats(bundle)}
        for apm in self.APM_NAMES:
            if apm in all_names_lower:
                found_tools.add(apm)

        # Collect from job posting tech mentions across ALL categories —
        # observability tools surface in devops, security (Splunk), etc.
        if bundle.job_signals:
            for tm in bundle.job_signals.tech_mentions:
                name_lower = tm.name.lower()
                for apm in self.APM_NAMES:
                    if apm in name_lower:
                        found_tools.add(tm.name)  # preserve original casing
                        break

        if found_tools:
            # Surface the specific tools so sellers can build displacement strategies
            return PainInference(
                rule_id="observability_stack_detected",
                title="Observability Stack Detected",
                description="Specific observability/APM tools identified via tech detection or job postings.",
                severity="info",
                evidence=[f"Tools found: {', '.join(sorted(found_tools))}"],
                confidence=70,
                category="operations",
            )

        # SRE/DevOps hiring implies observability tooling even if we can't name it
        if bundle.job_signals:
            if any(r in ("devops",) for r in bundle.job_signals.role_types):
                return None

        return PainInference(
            rule_id="observability_gap",
            title="Observability Gap",
            description="Product subdomains detected but no APM/monitoring tools found, suggesting limited observability.",
            severity="low",
            evidence=[f"Product subdomains: {', '.join(product_subdomains)}", "No APM/monitoring tools detected"],
            confidence=25,
            category="operations",
        )

    def _database_scaling_pressure(self, bundle: SignalBundle) -> Optional[PainInference]:
        all_names_lower = {n.lower() for n, _ in self._get_all_tech_names_and_cats(bundle)}

        # Find database techs (excluding analytics DBs)
        dbs_found = {n for n in all_names_lower if n in self.DATABASE_NAMES}
        if len(dbs_found) != 1:
            return None

        # Check for caching layer
        has_cache = any(n in all_names_lower for n in self.CACHE_NAMES)
        if has_cache:
            return None

        # Check for data/backend hiring
        js = bundle.job_signals
        if not js:
            return None
        has_hiring = any(r in ("data", "backend") for r in js.role_types)
        if not has_hiring:
            return None

        db_name = next(iter(dbs_found))
        return PainInference(
            rule_id="database_scaling_pressure",
            title="Database Scaling Pressure",
            description="Single database with data/backend hiring and no caching layer suggests database scaling challenges.",
            severity="medium",
            evidence=[f"Single database: {db_name}", f"Hiring signals: {', '.join(js.role_types)}", "No caching layer detected"],
            confidence=55,
            category="engineering",
        )

    def _auth_fragmentation(self, bundle: SignalBundle) -> Optional[PainInference]:
        tech_by_domain = self._get_tech_names_by_domain(bundle)
        provider_domains: dict[str, list[str]] = {}

        for domain, names in tech_by_domain.items():
            for name in names:
                nl = name.lower()
                # Check against known auth provider names
                for provider in self.AUTH_PROVIDER_NAMES:
                    if provider in nl:
                        provider_domains.setdefault(name, []).append(domain)
                        break
                # Also check for security-category techs containing "auth" or "sso"

        # Also check category-based detection
        for domain, stack in bundle.tech_by_domain.items():
            techs = []
            if isinstance(stack, TechStack):
                techs = [(t.name, (t.category or "").lower()) for t in stack.technologies]
            elif isinstance(stack, dict):
                techs = [(t.get("name", ""), (t.get("category", "") or "").lower()) for t in stack.get("technologies", [])]
            for name, cat in techs:
                if "security" in cat and ("auth" in name.lower() or "sso" in name.lower()):
                    if name not in provider_domains:
                        provider_domains.setdefault(name, []).append(domain)
                    elif domain not in provider_domains[name]:
                        provider_domains[name].append(domain)

        if len(provider_domains) >= 2:
            evidence = [f"{provider} on {', '.join(domains)}" for provider, domains in provider_domains.items()]
            return PainInference(
                rule_id="auth_fragmentation",
                title="Auth Fragmentation",
                description="Multiple distinct auth/identity providers detected, suggesting fragmented identity management.",
                severity="medium",
                evidence=evidence,
                confidence=50,
                category="operations",
            )
        return None

    def _evaluate_compounds(self, results: list[PainInference]) -> None:
        """Second pass: check for compound rule patterns and append new inferences."""
        fired_ids = {r.rule_id for r in results}
        confidence_map = {r.rule_id: r.confidence for r in results}

        compounds = [
            {
                "rule_id": "systemic_security_underinvestment",
                "title": "Systemic Security Underinvestment",
                "description": "Multiple independent security signals compound into evidence of systemic security underinvestment.",
                "severity": "high",
                "category": "security",
                "constituents": ["security_gap", "cert_gap"],
                "min_matches": 2,
            },
            {
                "rule_id": "engineering_capacity_crisis",
                "title": "Engineering Capacity Crisis",
                "description": "Multiple engineering stress signals compound into evidence of an engineering capacity crisis.",
                "severity": "high",
                "category": "engineering",
                "constituents": ["tech_debt", "scaling_pressure", "hiring_velocity_anomaly"],
                "min_matches": 2,
            },
            {
                "rule_id": "marketing_infra_debt",
                "title": "Marketing Infrastructure Debt",
                "description": "Multiple marketing/analytics signals compound into evidence of marketing infrastructure debt.",
                "severity": "medium",
                "category": "marketing",
                "constituents": ["identity_fragmentation", "tag_bloat", "marketing_product_mismatch"],
                "min_matches": 2,
            },
        ]

        for compound in compounds:
            matched = [c for c in compound["constituents"] if c in fired_ids]
            if len(matched) >= compound["min_matches"]:
                conf = min(max(confidence_map[m] for m in matched) + 10, 95)
                results.append(PainInference(
                    rule_id=compound["rule_id"],
                    title=compound["title"],
                    description=compound["description"],
                    severity=compound["severity"],
                    evidence=[f"Triggered by: {', '.join(matched)}"],
                    confidence=conf,
                    category=compound["category"],
                ))

    def _apply_dampeners(self, results: list[PainInference], bundle: SignalBundle) -> None:
        """Third pass: reduce confidence when mitigating signals are present."""
        fired_ids = {r.rule_id for r in results}
        result_map = {r.rule_id: r for r in results}

        # systemic_security_underinvestment: if cert_gap fired but SSL has automation_inferred
        if "systemic_security_underinvestment" in result_map:
            if "cert_gap" in fired_ids and bundle.infra and bundle.infra.ssl_automation_inferred:
                result_map["systemic_security_underinvestment"].confidence -= 15

        # observability_gap: if devops in job role_types (they're hiring for it)
        if "observability_gap" in result_map:
            if bundle.job_signals and "devops" in bundle.job_signals.role_types:
                result_map["observability_gap"].confidence -= 10

        # database_scaling_pressure: if data tech mentions include Spark/Kafka/Airflow
        if "database_scaling_pressure" in result_map and bundle.job_signals:
            data_platform_tools = {"spark", "kafka", "airflow"}
            for tm in bundle.job_signals.tech_mentions:
                if tm.name.lower() in data_platform_tools:
                    result_map["database_scaling_pressure"].confidence -= 10
                    break

        # tool_sprawl: more subdomains = more tech expected
        if "tool_sprawl" in result_map:
            num_subdomains = len(bundle.tech_by_domain)
            if num_subdomains > 3:
                extra = num_subdomains - 3
                result_map["tool_sprawl"].confidence -= 10 * extra
                result_map["tool_sprawl"].confidence = max(result_map["tool_sprawl"].confidence, 30)

        # Floor all confidences at 10 (seller weighting may override to 0 later)
        for r in results:
            if r.confidence < 10:
                r.confidence = 10

    def _compute_category_relevance(self, seller: SellerContext) -> dict[str, int]:
        """Check problems_solved for substring matches per category. Return hit counts."""
        text = seller.problems_solved.lower()
        relevance: dict[str, int] = {}
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in text)
            relevance[category] = hits
        return relevance

    # Maps seller category → pain rule_ids that get extra boost (2x weight)
    _SELLER_CATEGORY_BOOSTS: dict[str, set[str]] = {
        "database": {"database_scaling_pressure", "data_infra_pain", "scaling_pressure", "tech_debt"},
        "fintech": {"compliance_gap", "security_gap", "cert_gap"},
        "healthtech": {"compliance_gap", "security_gap"},
        "martech": {"identity_fragmentation", "tag_bloat", "marketing_product_mismatch"},
        "devtools": {"observability_gap", "observability_stack_detected", "tool_sprawl", "scaling_pressure", "tech_debt"},
    }

    def _apply_seller_weighting(self, results: list[PainInference], seller: SellerContext,
                                seller_category: str = "") -> None:
        """Boost/dampen confidence based on seller's product relevance to each category.

        Two-layer boosting:
        1. Category-level: +15 for matching pain categories (existing)
        2. Rule-level: +15 extra for specific pain rules aligned to seller category (new)
        """
        relevance = self._compute_category_relevance(seller)
        max_hits = max(relevance.values()) if relevance else 0

        # Hard-suppress security signals for non-security sellers (before early return)
        sells_security = relevance.get("security", 0) >= 1
        if not sells_security:
            for r in results:
                if r.category == "security":
                    r.confidence = 0

        if max_hits == 0 and not seller_category:
            return

        # Layer 1: category-level boost/dampen
        for r in results:
            if not r.category or r.confidence == 0:
                continue
            hits = relevance.get(r.category, 0)
            if hits >= 1:
                r.confidence += 15
            elif max_hits >= 2:
                r.confidence -= 10

        # Layer 2: rule-level boost for seller-aligned pain signals
        if seller_category:
            boosted_rules = self._SELLER_CATEGORY_BOOSTS.get(seller_category, set())
            if boosted_rules:
                for r in results:
                    if r.rule_id in boosted_rules and r.confidence > 0:
                        r.confidence += 15

        # Professional services bonus: operations and data are universally relevant
        if seller.product_type == "msp":
            for r in results:
                if r.category in ("operations", "data"):
                    r.confidence += 5

        # Clamp all to [10, 95] (suppressed signals stay at 0)
        for r in results:
            if r.confidence > 0:
                r.confidence = max(10, min(95, r.confidence))

    def _apply_detection_confidence(self, results: list[PainInference], bundle: SignalBundle) -> None:
        """Adjust pain confidence based on underlying tech detection confidence."""
        all_confidences = {}
        for domain, stack in bundle.tech_by_domain.items():
            if isinstance(stack, TechStack):
                for t in stack.technologies:
                    all_confidences[t.name.lower()] = t.confidence or 100
            elif isinstance(stack, dict):
                for t in stack.get("technologies", []):
                    name = t.get("name")
                    if not name:
                        continue
                    all_confidences[name.lower()] = t.get("confidence", 100) or 100

        for r in results:
            # Match evidence tech names against detection confidences
            relevant = [c for name, c in all_confidences.items()
                        if any(name in ev.lower() for ev in r.evidence)]
            if not relevant:
                continue
            avg = sum(relevant) / len(relevant)
            if avg < 40:
                r.confidence -= 20
            elif avg < 60:
                r.confidence -= 10
            r.confidence = max(10, min(95, r.confidence))
