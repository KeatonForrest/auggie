"""Pain inference engine — derive actionable pain signals from collected data."""

from typing import Optional
from models import SignalBundle, PainInference, TechStack


class PainInferenceEngine:
    """Evaluate a SignalBundle and return scored pain inferences."""

    def evaluate(self, bundle: SignalBundle) -> list[PainInference]:
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
        ]
        results = []
        for rule in rules:
            inference = rule(bundle)
            if inference:
                results.append(inference)
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
        # Check for PHP < 8 via version
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
            )
        return None

    def _data_infra_pain(self, bundle: SignalBundle) -> Optional[PainInference]:
        js = bundle.job_signals
        if not js:
            return None
        data_roles = [r for r in js.role_types if r == "data"]
        if len(data_roles) >= 1:
            # Check for 2+ data-related role *mentions* in seniority
            data_count = sum(js.seniority_distribution.values())
            if data_count >= 2 or len(data_roles) >= 1:
                return PainInference(
                    rule_id="data_infra_pain",
                    title="Data Infrastructure Growth Pain",
                    description="Multiple data-related roles signal growing data infrastructure needs.",
                    severity="medium",
                    evidence=[f"Data role types: {', '.join(js.role_types)}", f"Total roles parsed: {js.total_roles_parsed}"],
                    confidence=50,
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
            )
        return None
