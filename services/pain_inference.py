"""Pain inference engine — derive actionable pain signals from collected data."""

from typing import Optional
from models import SignalBundle, PainInference, TechStack, SellerContext


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

    def evaluate(self, bundle: SignalBundle, seller: Optional[SellerContext] = None) -> list[PainInference]:
        rules = [
            self._identity_fragmentation,
            self._tech_debt,
            self._security_gap,
            self._scaling_pressure,
            self._multi_cloud,
            self._email_risk,
            self._cert_gap,
            self._marketing_product_mismatch,
            self._data_infra_pain,
            self._tag_bloat,
            self._vendor_lock_in,
            self._compliance_gap,
            self._frontend_performance_debt,
            self._hiring_velocity_anomaly,
            self._tool_sprawl,
            self._observability_gap,
            self._database_scaling_pressure,
            self._auth_fragmentation,
        ]
        results = []
        for rule in rules:
            inference = rule(bundle)
            if inference:
                results.append(inference)
        self._evaluate_compounds(results)
        self._apply_dampeners(results, bundle)
        if seller is not None:
            self._apply_seller_weighting(results, seller)
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
        sp = bundle.security_posture
        dns = bundle.dns_profile
        if sp and sp.score <= 2:
            missing_email = dns and (not dns.has_dmarc or not dns.has_spf)
            if missing_email:
                evidence = [f"Security header score: {sp.score}/6 (grade {sp.grade})", f"Missing headers: {', '.join(sp.missing[:3])}"]
                if dns and not dns.has_dmarc:
                    evidence.append("No DMARC record")
                if dns and not dns.has_spf:
                    evidence.append("No SPF record")
                return PainInference(
                    rule_id="security_gap",
                    title="Security Posture Gap",
                    description="Weak security headers combined with missing email authentication signals broad security underinvestment.",
                    severity="high",
                    evidence=evidence,
                    confidence=80,
                    category="security",
                )
        return None

    def _scaling_pressure(self, bundle: SignalBundle) -> Optional[PainInference]:
        js = bundle.job_signals
        if not js:
            return None
        devops_roles = [r for r in js.role_types if r in ("devops", "security")]
        cloud_hints = bundle.dns_profile.cloud_provider_hints if bundle.dns_profile else []
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
        if bundle.dns_profile:
            clouds.update(bundle.dns_profile.cloud_provider_hints)
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
        dns = bundle.dns_profile
        if not dns:
            return None
        issues = []
        if not dns.has_spf:
            issues.append("Missing SPF record")
        if not dns.has_dkim:
            issues.append("Missing DKIM record")
        if dns.has_dmarc and dns.dmarc_policy == "none":
            issues.append("DMARC policy set to 'none' (monitoring only)")
        elif not dns.has_dmarc:
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
        ssl = bundle.ssl_profile
        if not ssl:
            return None
        if ssl.expiry_days is not None and ssl.expiry_days < 30 and not ssl.automation_inferred:
            return PainInference(
                rule_id="cert_gap",
                title="Certificate Expiry Risk",
                description="SSL certificate expiring soon without automated renewal detected.",
                severity="high",
                evidence=[f"Certificate expires in {ssl.expiry_days} days", f"Issuer: {ssl.issuer or 'unknown'}", "No automation (e.g. Let's Encrypt) detected"],
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
            data_count = sum(js.seniority_distribution.values())
            if data_count >= 2 or len(data_roles) >= 1:
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
        dns = bundle.dns_profile
        if dns:
            for vendor, keywords in [("AWS", ["aws", "amazon"]), ("Azure", ["azure", "microsoft"]), ("GCP", ["gcp", "google"])]:
                if dns.ns_provider and any(k in dns.ns_provider.lower() for k in keywords):
                    vendor_sources.setdefault(vendor, set()).add("DNS NS")
                if dns.mx_provider and any(k in dns.mx_provider.lower() for k in keywords):
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
        sp = bundle.security_posture
        dns = bundle.dns_profile
        js = bundle.job_signals
        if not sp or sp.score > 2:
            return None
        if not dns or (dns.has_dmarc and dns.has_spf):
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
        evidence = [f"Security header grade: {sp.grade} ({sp.score}/6)"]
        if not dns.has_dmarc:
            evidence.append("Missing DMARC")
        if not dns.has_spf:
            evidence.append("Missing SPF")
        evidence.append("Security-related hiring signals detected")
        return PainInference(
            rule_id="compliance_gap",
            title="Compliance Gap",
            description="Weak security posture combined with missing email auth and security hiring signals suggests compliance exposure.",
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

        # Check all tech names for APM tools
        all_names_lower = {n.lower() for n, _ in self._get_all_tech_names_and_cats(bundle)}
        has_apm = any(apm in all_names_lower for apm in self.APM_NAMES)

        # Also check job_signals tech_mentions in devops category for monitoring keywords
        if not has_apm and bundle.job_signals:
            monitoring_keywords = {"monitoring", "observability", "apm", "alerting", "tracing"}
            for tm in bundle.job_signals.tech_mentions:
                if tm.category == "devops" and any(k in tm.name.lower() for k in monitoring_keywords | self.APM_NAMES):
                    has_apm = True
                    break

        if not has_apm:
            return PainInference(
                rule_id="observability_gap",
                title="Observability Gap",
                description="Product subdomains detected but no APM/monitoring tools found, suggesting limited observability.",
                severity="low",
                evidence=[f"Product subdomains: {', '.join(product_subdomains)}", "No APM/monitoring tools detected"],
                confidence=40,
                category="operations",
            )
        return None

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
                "constituents": ["security_gap", "email_risk", "cert_gap"],
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
            if "cert_gap" in fired_ids and bundle.ssl_profile and bundle.ssl_profile.automation_inferred:
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

        # Floor all confidences at 10
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

    def _apply_seller_weighting(self, results: list[PainInference], seller: SellerContext) -> None:
        """Boost/dampen confidence based on seller's product relevance to each category."""
        relevance = self._compute_category_relevance(seller)
        max_hits = max(relevance.values()) if relevance else 0
        if max_hits == 0:
            return

        for r in results:
            if not r.category:
                continue
            hits = relevance.get(r.category, 0)
            if hits >= 1:
                r.confidence += 15
            elif max_hits >= 2:
                r.confidence -= 10

        # MSP bonus
        if seller.product_type == "msp":
            for r in results:
                if r.category in ("operations", "security"):
                    r.confidence += 5

        # Clamp all to [10, 95]
        for r in results:
            r.confidence = max(10, min(95, r.confidence))
