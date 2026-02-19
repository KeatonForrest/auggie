"""Tests for services/pain_inference.py"""

import pytest
from unittest.mock import patch, MagicMock
from services.pain_inference import PainInferenceEngine, detect_seller_category, is_action_tier_relevant
from models import (
    SignalBundle, DNSProfile, SSLProfile, SecurityPosture,
    RobotsSignals, JobSignals, TechMention, TechStack, DetectedTechnology,
    SellerContext, PainInference,
)


@pytest.fixture
def engine():
    return PainInferenceEngine()


@pytest.fixture
def engine_frontend_on():
    """Engine fixture that patches pain_frontend_rule_enabled=True."""
    return PainInferenceEngine()


def _make_stack(*techs):
    """Helper: create TechStack from (name, category) tuples."""
    return TechStack(technologies=[
        DetectedTechnology(name=n, category=c, confidence=100) for n, c in techs
    ])


class TestIdentityFragmentation:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("GA4", "analytics"), ("Hotjar", "analytics"),
                ("Mixpanel", "analytics"), ("GTM", "tag manager"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "identity_fragmentation" in ids

    def test_no_trigger_with_cdp(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("GA4", "analytics"), ("Hotjar", "analytics"),
                ("Mixpanel", "analytics"), ("Segment", "cdp"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "identity_fragmentation" not in ids


class TestTechDebt:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("AngularJS", "framework"), ("React", "framework"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "tech_debt" in ids

    def test_no_trigger_modern_only(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(("React", "framework"),)},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "tech_debt" not in ids


class TestSecurityGap:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["strict-transport-security", "content-security-policy", "x-frame-options", "referrer-policy", "permissions-policy"], grade="D"),
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dmarc=False),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "security_gap" in ids

    def test_no_trigger_good_headers(self, engine):
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=5, present=["a", "b", "c", "d", "e"], missing=["f"], grade="B"),
            dns_profile=DNSProfile(domain="x.com", has_spf=True, has_dmarc=True),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "security_gap" not in ids


class TestScalingPressure:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            job_signals=JobSignals(role_types=["devops"], tech_mentions=[]),
            dns_profile=DNSProfile(domain="x.com", cloud_provider_hints=["AWS"]),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "scaling_pressure" in ids

    def test_no_trigger_no_devops(self, engine):
        bundle = SignalBundle(
            job_signals=JobSignals(role_types=["backend"], tech_mentions=[]),
            dns_profile=DNSProfile(domain="x.com", cloud_provider_hints=["AWS"]),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "scaling_pressure" not in ids


class TestMultiCloud:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", cloud_provider_hints=["AWS"]),
            tech_by_domain={"x.com": _make_stack(("Azure Functions", "cloud"),)},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "multi_cloud" in ids

    def test_no_trigger_single(self, engine):
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", cloud_provider_hints=["AWS"]),
            tech_by_domain={"x.com": _make_stack(("S3", "storage"),)},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "multi_cloud" not in ids


class TestEmailRisk:
    def test_email_risk_rule_disabled(self, engine):
        """email_risk rule is fully disabled — never fires."""
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dkim=False, has_dmarc=False),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "email_risk" not in ids


class TestCertGap:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            ssl_profile=SSLProfile(domain="x.com", issuer="DigiCert", expiry_days=10, automation_inferred=False),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "cert_gap" in ids

    def test_no_trigger_letsencrypt(self, engine):
        bundle = SignalBundle(
            ssl_profile=SSLProfile(domain="x.com", issuer="Let's Encrypt", expiry_days=10, automation_inferred=True),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "cert_gap" not in ids


class TestMarketingProductMismatch:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            tech_by_domain={
                "example.com": _make_stack(("WordPress", "javascript framework"),),
                "app.example.com": _make_stack(("React", "javascript framework"),),
            },
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "marketing_product_mismatch" in ids

    def test_no_trigger_same_fw(self, engine):
        bundle = SignalBundle(
            tech_by_domain={
                "example.com": _make_stack(("React", "javascript framework"),),
                "app.example.com": _make_stack(("React", "javascript framework"),),
            },
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "marketing_product_mismatch" not in ids


class TestDataInfraPain:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            job_signals=JobSignals(role_types=["data", "backend"], seniority_distribution={"senior": 2, "mid": 1}, tech_mentions=[]),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "data_infra_pain" in ids

    def test_no_trigger_no_data(self, engine):
        bundle = SignalBundle(
            job_signals=JobSignals(role_types=["backend"], seniority_distribution={}, tech_mentions=[]),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "data_infra_pain" not in ids


class TestTagBloat:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("GA4", "analytics"), ("Hotjar", "analytics"), ("Mixpanel", "analytics"),
                ("GTM", "tag manager"), ("FB Pixel", "advertising"), ("LinkedIn", "advertising"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "tag_bloat" in ids

    def test_no_trigger_few(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(("GA4", "analytics"),)},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "tag_bloat" not in ids


class TestVendorLockIn:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", ns_provider="Amazon Route 53", mx_provider="Amazon SES"),
            tech_by_domain={"x.com": _make_stack(("AWS CloudFront", "cdn"),)},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "vendor_lock_in" in ids

    def test_no_trigger_few_sources(self, engine):
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", ns_provider="Amazon Route 53"),
            tech_by_domain={"x.com": _make_stack(("React", "framework"),)},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "vendor_lock_in" not in ids


class TestComplianceGap:
    def test_triggers(self, engine):
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="F"),
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dmarc=False),
            job_signals=JobSignals(role_types=["security"], tech_mentions=[], seniority_distribution={}),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "compliance_gap" in ids

    def test_no_trigger_good_score(self, engine):
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=5, present=["a", "b", "c", "d", "e"], missing=["f"], grade="B"),
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dmarc=False),
            job_signals=JobSignals(role_types=["security"], tech_mentions=[], seniority_distribution={}),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "compliance_gap" not in ids


class TestFrontendPerformanceDebt:
    @patch("services.pain_inference.get_settings")
    def test_triggers(self, mock_settings, engine):
        mock_settings.return_value = MagicMock(pain_frontend_rule_enabled=True)
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("React", "javascript framework"), ("Vue", "javascript framework"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "frontend_performance_debt" in ids

    @patch("services.pain_inference.get_settings")
    def test_no_trigger_with_cdn(self, mock_settings, engine):
        mock_settings.return_value = MagicMock(pain_frontend_rule_enabled=True)
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("React", "javascript framework"), ("Vue", "javascript framework"),
                ("Cloudflare", "cdn"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "frontend_performance_debt" not in ids

    @patch("services.pain_inference.get_settings")
    def test_no_trigger_meta_framework_pair(self, mock_settings, engine):
        """Next.js + React should not fire since Next.js wraps React."""
        mock_settings.return_value = MagicMock(pain_frontend_rule_enabled=True)
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("Next.js", "javascript framework"), ("React", "javascript framework"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "frontend_performance_debt" not in ids


class TestHiringVelocityAnomaly:
    def test_triggers_top_heavy(self, engine):
        bundle = SignalBundle(
            job_signals=JobSignals(role_types=["backend"], tech_mentions=[],
                                   seniority_distribution={"senior": 2, "staff": 1, "principal": 1}),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "hiring_velocity_anomaly" in ids
        title = next(r.title for r in results if r.rule_id == "hiring_velocity_anomaly")
        assert title == "Execution Bottleneck"

    def test_triggers_bottom_heavy(self, engine):
        bundle = SignalBundle(
            job_signals=JobSignals(role_types=["backend"], tech_mentions=[],
                                   seniority_distribution={"junior": 2, "mid": 2}),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "hiring_velocity_anomaly" in ids
        title = next(r.title for r in results if r.rule_id == "hiring_velocity_anomaly")
        assert title == "Leadership Gap"

    def test_no_trigger_balanced(self, engine):
        bundle = SignalBundle(
            job_signals=JobSignals(role_types=["backend"], tech_mentions=[],
                                   seniority_distribution={"senior": 2, "mid": 2}),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "hiring_velocity_anomaly" not in ids


class TestToolSprawl:
    def test_triggers(self, engine):
        techs = [(f"Tool{i}", "misc") for i in range(40)]
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(*techs)},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "tool_sprawl" in ids

    def test_no_trigger_few(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(("React", "framework"), ("Vue", "framework"))},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "tool_sprawl" not in ids


class TestObservabilityGap:
    def test_triggers(self, engine):
        """Product subdomain with no APM tools should fire."""
        bundle = SignalBundle(
            tech_by_domain={
                "app.example.com": _make_stack(("React", "javascript framework"),),
            },
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "observability_gap" in ids
        r = next(r for r in results if r.rule_id == "observability_gap")
        assert r.confidence == 25
        assert r.severity == "low"
        assert r.category == "operations"

    def test_no_trigger_no_product_subdomain(self, engine):
        """No product subdomains = no fire."""
        bundle = SignalBundle(
            tech_by_domain={
                "example.com": _make_stack(("React", "javascript framework"),),
            },
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "observability_gap" not in ids

    def test_no_trigger_with_apm(self, engine):
        """APM tool detected = gap doesn't fire, stack detected does."""
        bundle = SignalBundle(
            tech_by_domain={
                "app.example.com": _make_stack(
                    ("React", "javascript framework"), ("Sentry", "error tracking"),
                ),
            },
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "observability_gap" not in ids
        assert "observability_stack_detected" in ids
        r = next(r for r in results if r.rule_id == "observability_stack_detected")
        assert "sentry" in r.evidence[0].lower()

    def test_no_trigger_with_devops_monitoring_mention(self, engine):
        """Monitoring mentioned in job postings = gap doesn't fire, stack surfaces tools."""
        bundle = SignalBundle(
            tech_by_domain={
                "dashboard.example.com": _make_stack(("Vue", "javascript framework"),),
            },
            job_signals=JobSignals(
                role_types=["devops"],
                tech_mentions=[TechMention(name="Datadog", category="devops", count=2)],
            ),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "observability_gap" not in ids
        assert "observability_stack_detected" in ids
        r = next(r for r in results if r.rule_id == "observability_stack_detected")
        assert "Datadog" in r.evidence[0]

    def test_stack_detected_from_job_postings_chronosphere(self, engine):
        """Chronosphere in job postings should surface for displacement sellers."""
        bundle = SignalBundle(
            tech_by_domain={
                "app.example.com": _make_stack(("React", "javascript framework"),),
            },
            job_signals=JobSignals(
                role_types=["backend"],
                tech_mentions=[TechMention(name="Chronosphere", category="devops", count=1)],
            ),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "observability_stack_detected" in ids
        assert "observability_gap" not in ids
        r = next(r for r in results if r.rule_id == "observability_stack_detected")
        assert "Chronosphere" in r.evidence[0]
        assert r.confidence == 70


class TestDatabaseScalingPressure:
    def test_triggers(self, engine):
        """Single DB + data/backend hiring + no cache = fire."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(("PostgreSQL", "database"),)},
            job_signals=JobSignals(role_types=["backend", "data"], tech_mentions=[]),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "database_scaling_pressure" in ids
        r = next(r for r in results if r.rule_id == "database_scaling_pressure")
        assert r.confidence == 55
        assert r.severity == "medium"
        assert r.category == "engineering"

    def test_no_trigger_multiple_dbs(self, engine):
        """2 databases = no fire."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("PostgreSQL", "database"), ("MongoDB", "database"),
            )},
            job_signals=JobSignals(role_types=["backend"], tech_mentions=[]),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "database_scaling_pressure" not in ids

    def test_no_trigger_with_cache(self, engine):
        """Cache present = no fire."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("PostgreSQL", "database"), ("Redis", "cache"),
            )},
            job_signals=JobSignals(role_types=["backend"], tech_mentions=[]),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "database_scaling_pressure" not in ids

    def test_no_trigger_no_hiring(self, engine):
        """No data/backend hiring = no fire."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(("PostgreSQL", "database"),)},
            job_signals=JobSignals(role_types=["frontend"], tech_mentions=[]),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "database_scaling_pressure" not in ids


class TestAuthFragmentation:
    def test_triggers(self, engine):
        """2+ auth providers = fire."""
        bundle = SignalBundle(
            tech_by_domain={
                "app.example.com": _make_stack(("Auth0", "security"),),
                "admin.example.com": _make_stack(("Okta", "security"),),
            },
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "auth_fragmentation" in ids
        r = next(r for r in results if r.rule_id == "auth_fragmentation")
        assert r.confidence == 50
        assert r.severity == "medium"
        assert r.category == "operations"

    def test_no_trigger_single_provider(self, engine):
        """Only 1 auth provider = no fire."""
        bundle = SignalBundle(
            tech_by_domain={
                "app.example.com": _make_stack(("Auth0", "security"),),
                "admin.example.com": _make_stack(("React", "framework"),),
            },
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "auth_fragmentation" not in ids

    def test_triggers_with_security_category_auth(self, engine):
        """Security category tech with 'auth' in name should also count."""
        bundle = SignalBundle(
            tech_by_domain={
                "app.example.com": _make_stack(("Auth0", "security"),),
                "admin.example.com": _make_stack(("CustomSSO", "security"),),
            },
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "auth_fragmentation" in ids


class TestCompoundRules:
    def test_systemic_security(self, engine):
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dkim=False, has_dmarc=False),
            ssl_profile=SSLProfile(domain="x.com", issuer="DigiCert", expiry_days=10, automation_inferred=False),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "security_gap" in ids
        assert "cert_gap" in ids
        assert "systemic_security_underinvestment" in ids

    def test_engineering_capacity_crisis(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(("AngularJS", "framework"), ("React", "framework"))},
            job_signals=JobSignals(role_types=["devops"], tech_mentions=[],
                                   seniority_distribution={"senior": 2, "staff": 1, "principal": 1}),
            dns_profile=DNSProfile(domain="x.com", cloud_provider_hints=["AWS"]),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "tech_debt" in ids
        assert "scaling_pressure" in ids
        assert "hiring_velocity_anomaly" in ids
        assert "engineering_capacity_crisis" in ids

    def test_marketing_infra_debt(self, engine):
        bundle = SignalBundle(
            tech_by_domain={
                "x.com": _make_stack(
                    ("GA4", "analytics"), ("Hotjar", "analytics"), ("Mixpanel", "analytics"),
                    ("GTM", "tag manager"), ("FB Pixel", "advertising"), ("LinkedIn", "advertising"),
                    ("WordPress", "javascript framework"),
                ),
                "app.x.com": _make_stack(("React", "javascript framework"),),
            },
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "identity_fragmentation" in ids
        assert "tag_bloat" in ids
        assert "marketing_product_mismatch" in ids
        assert "marketing_infra_debt" in ids

    def test_no_compound_without_constituents(self, engine):
        bundle = SignalBundle()
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "systemic_security_underinvestment" not in ids
        assert "engineering_capacity_crisis" not in ids
        assert "marketing_infra_debt" not in ids

    def test_compound_confidence_capped(self, engine):
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dkim=False, has_dmarc=False),
            ssl_profile=SSLProfile(domain="x.com", issuer="DigiCert", expiry_days=10, automation_inferred=False),
        )
        results = engine.evaluate(bundle)
        compound = next(r for r in results if r.rule_id == "systemic_security_underinvestment")
        assert compound.confidence <= 95


class TestDampeners:
    def test_observability_gap_suppressed_by_devops_hiring(self, engine):
        """DevOps/SRE hiring implies observability tooling — rule should not fire."""
        bundle = SignalBundle(
            tech_by_domain={
                "app.example.com": _make_stack(("React", "javascript framework"),),
            },
            job_signals=JobSignals(role_types=["devops"], tech_mentions=[]),
        )
        results = engine.evaluate(bundle)
        r = next((r for r in results if r.rule_id == "observability_gap"), None)
        assert r is None

    def test_database_scaling_dampened_by_data_platform(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(("PostgreSQL", "database"),)},
            job_signals=JobSignals(
                role_types=["backend", "data"],
                tech_mentions=[TechMention(name="Kafka", category="data", count=1)],
            ),
        )
        results = engine.evaluate(bundle)
        r = next((r for r in results if r.rule_id == "database_scaling_pressure"), None)
        assert r is not None
        assert r.confidence == 45  # 55 - 10

    def test_tool_sprawl_dampened_by_many_subdomains(self, engine):
        # 5 subdomains = 2 extra beyond 3 = -20, but floor at 30
        techs = [(f"Tool{i}", "misc") for i in range(40)]
        bundle = SignalBundle(
            tech_by_domain={
                "a.com": _make_stack(*techs[:10]),
                "b.com": _make_stack(*techs[10:20]),
                "c.com": _make_stack(*techs[20:28]),
                "d.com": _make_stack(*techs[28:35]),
                "e.com": _make_stack(*techs[35:]),
            },
        )
        results = engine.evaluate(bundle)
        r = next((r for r in results if r.rule_id == "tool_sprawl"), None)
        assert r is not None
        assert r.confidence == 35  # 55 - 20

    def test_tool_sprawl_floor_at_30(self, engine):
        # 7 subdomains = 4 extra = -40, but floor at 30
        techs = [(f"Tool{i}", "misc") for i in range(42)]
        bundle = SignalBundle(
            tech_by_domain={
                f"sub{i}.com": _make_stack(*techs[i*6:(i+1)*6]) for i in range(7)
            },
        )
        results = engine.evaluate(bundle)
        r = next((r for r in results if r.rule_id == "tool_sprawl"), None)
        assert r is not None
        assert r.confidence == 30

    def test_confidence_floor_at_10(self, engine):
        """All confidences should be floored at 10."""
        # This is tested implicitly but let's verify the floor works
        bundle = SignalBundle(
            tech_by_domain={
                "app.example.com": _make_stack(("React", "javascript framework"),),
            },
            job_signals=JobSignals(role_types=["devops"], tech_mentions=[]),
        )
        results = engine.evaluate(bundle)
        for r in results:
            assert r.confidence >= 10


class TestCategories:
    def test_all_rules_have_category(self, engine):
        """Every fired rule should have a non-empty category."""
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dkim=False, has_dmarc=False),
            ssl_profile=SSLProfile(domain="x.com", issuer="DigiCert", expiry_days=10, automation_inferred=False),
            tech_by_domain={
                "x.com": _make_stack(
                    ("GA4", "analytics"), ("Hotjar", "analytics"), ("Mixpanel", "analytics"),
                    ("GTM", "tag manager"), ("FB Pixel", "advertising"), ("LinkedIn", "advertising"),
                    ("AngularJS", "framework"), ("React", "framework"),
                ),
                "app.x.com": _make_stack(("Vue", "javascript framework"),),
            },
            job_signals=JobSignals(
                role_types=["devops", "data", "backend", "security"],
                tech_mentions=[],
                seniority_distribution={"senior": 2, "staff": 1, "principal": 1},
            ),
        )
        results = engine.evaluate(bundle)
        for r in results:
            assert r.category, f"Rule {r.rule_id} has no category"

    def test_category_values(self, engine):
        """Spot-check some category assignments."""
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
        )
        results = engine.evaluate(bundle)
        gap = next(r for r in results if r.rule_id == "security_gap")
        assert gap.category == "security"


class TestEvaluate:
    def test_sorted_by_confidence(self, engine):
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dkim=False, has_dmarc=False),
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
            ssl_profile=SSLProfile(domain="x.com", issuer="DigiCert", expiry_days=5, automation_inferred=False),
        )
        results = engine.evaluate(bundle)
        confs = [r.confidence for r in results]
        assert confs == sorted(confs, reverse=True)

    def test_empty_bundle(self, engine):
        results = engine.evaluate(SignalBundle())
        assert results == []


class TestSellerWeighting:
    def test_seller_weighting_boosts_relevant(self, engine):
        """Security seller → security signals get +15."""
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
        )
        # Without seller
        base_results = engine.evaluate(bundle)
        base_conf = next(r.confidence for r in base_results if r.rule_id == "security_gap")

        # With security seller
        seller = SellerContext(problems_solved="We help with security compliance and threat detection")
        seller_results = engine.evaluate(bundle, seller=seller)
        seller_conf = next(r.confidence for r in seller_results if r.rule_id == "security_gap")
        assert seller_conf == base_conf + 15

    def test_seller_weighting_dampens_irrelevant(self, engine):
        """Security-focused seller → marketing signals get -10 when max hits >= 2."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("GA4", "analytics"), ("Hotjar", "analytics"),
                ("Mixpanel", "analytics"), ("GTM", "tag manager"),
                ("FB Pixel", "advertising"), ("LinkedIn", "advertising"),
            )},
        )
        # Without seller
        base_results = engine.evaluate(bundle)
        base_conf = next(r.confidence for r in base_results if r.rule_id == "tag_bloat")

        # With security seller (multiple security keyword hits → max_hits >= 2)
        seller = SellerContext(problems_solved="security compliance soc2 gdpr threat encryption")
        seller_results = engine.evaluate(bundle, seller=seller)
        seller_conf = next(r.confidence for r in seller_results if r.rule_id == "tag_bloat")
        assert seller_conf == base_conf - 10

    def test_seller_weighting_noop_no_seller(self, engine):
        """No seller = unchanged results."""
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dkim=False, has_dmarc=False),
        )
        results_no_seller = engine.evaluate(bundle)
        results_none = engine.evaluate(bundle, seller=None)
        assert [r.confidence for r in results_no_seller] == [r.confidence for r in results_none]

    def test_seller_weighting_msp_bonus(self, engine):
        """MSP product_type → +5 on operations/data categories."""
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dkim=False, has_dmarc=False,
                                   cloud_provider_hints=["AWS", "Azure"]),
        )
        # Operations seller, saas
        seller_saas = SellerContext(product_type="saas", problems_solved="cloud operations monitoring")
        results_saas = engine.evaluate(bundle, seller=seller_saas)
        conf_saas = next(r.confidence for r in results_saas if r.rule_id == "multi_cloud")

        # Operations seller, msp
        seller_msp = SellerContext(product_type="msp", problems_solved="cloud operations monitoring")
        results_msp = engine.evaluate(bundle, seller=seller_msp)
        conf_msp = next(r.confidence for r in results_msp if r.rule_id == "multi_cloud")

        assert conf_msp == conf_saas + 5

    def test_seller_weighting_empty_problems_solved_suppresses_security(self, engine):
        """Empty problems_solved → security signals suppressed."""
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
        )
        seller = SellerContext(problems_solved="")
        results = engine.evaluate(bundle, seller=seller)
        security_ids = [r.rule_id for r in results if r.category == "security"]
        assert "security_gap" not in security_ids

    def test_seller_weighting_irrelevant_problems_solved_suppresses_security(self, engine):
        """Irrelevant problems_solved (no category match) → security signals suppressed."""
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
        )
        seller = SellerContext(problems_solved="we sell office furniture and supplies")
        results = engine.evaluate(bundle, seller=seller)
        security_ids = [r.rule_id for r in results if r.category == "security"]
        assert "security_gap" not in security_ids

    def test_seller_weighting_msp_with_empty_problems_solved_suppresses_security(self, engine):
        """MSP seller with empty problems_solved → security signals suppressed (no auto-keep)."""
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
        )
        seller = SellerContext(product_type="msp", problems_solved="")
        results = engine.evaluate(bundle, seller=seller)
        security_ids = [r.rule_id for r in results if r.category == "security"]
        assert "security_gap" not in security_ids

    def test_seller_weighting_msp_with_security_problems_keeps_security(self, engine):
        """MSP seller with security keywords in problems_solved → security signals kept."""
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
        )
        seller = SellerContext(product_type="msp", problems_solved="security compliance threat")
        results = engine.evaluate(bundle, seller=seller)
        ids = [r.rule_id for r in results]
        assert "security_gap" in ids


def _make_stack_with_confidence(*techs):
    """Helper: create TechStack from (name, category, confidence) tuples."""
    return TechStack(technologies=[
        DetectedTechnology(name=n, category=c, confidence=conf) for n, c, conf in techs
    ])


class TestDetectionConfidence:
    def test_low_detection_confidence_dampens_pain(self, engine):
        """Tech detected at confidence 30 → pain rule gets -10."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack_with_confidence(
                ("GA4", "analytics", 30), ("Hotjar", "analytics", 30),
                ("Mixpanel", "analytics", 30), ("GTM", "tag manager", 30),
            )},
        )
        results = engine.evaluate(bundle)
        r = next(r for r in results if r.rule_id == "identity_fragmentation")
        # Base confidence is 75, avg detection confidence 30 < 40 → -20
        assert r.confidence == 55

    def test_high_detection_confidence_no_change(self, engine):
        """Tech at confidence 100 → pain rule unchanged."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack_with_confidence(
                ("GA4", "analytics", 100), ("Hotjar", "analytics", 100),
                ("Mixpanel", "analytics", 100), ("GTM", "tag manager", 100),
            )},
        )
        results = engine.evaluate(bundle)
        r = next(r for r in results if r.rule_id == "identity_fragmentation")
        assert r.confidence == 75

    def test_detection_confidence_with_no_tech_match(self, engine):
        """Non-tech rules (security headers) unaffected by detection confidence."""
        bundle = SignalBundle(
            security_posture=SecurityPosture(score=1, present=["x-content-type-options"], missing=["a", "b", "c", "d", "e"], grade="D"),
        )
        results_base = engine.evaluate(bundle)
        gap_conf = next(r.confidence for r in results_base if r.rule_id == "security_gap")
        assert gap_conf == 75

    def test_detection_confidence_dict_input_matches_techstack(self, engine):
        """Dict-shaped tech_by_domain should dampen identically to TechStack."""
        # TechStack version
        bundle_obj = SignalBundle(
            tech_by_domain={"x.com": _make_stack_with_confidence(
                ("GA4", "analytics", 30), ("Hotjar", "analytics", 30),
                ("Mixpanel", "analytics", 30), ("GTM", "tag manager", 30),
            )},
        )
        results_obj = engine.evaluate(bundle_obj)
        conf_obj = next(r.confidence for r in results_obj if r.rule_id == "identity_fragmentation")

        # Dict version with same confidence values
        bundle_dict = SignalBundle(
            tech_by_domain={"x.com": {
                "technologies": [
                    {"name": "GA4", "category": "analytics", "confidence": 30},
                    {"name": "Hotjar", "category": "analytics", "confidence": 30},
                    {"name": "Mixpanel", "category": "analytics", "confidence": 30},
                    {"name": "GTM", "category": "tag manager", "confidence": 30},
                ]
            }},
        )
        results_dict = engine.evaluate(bundle_dict)
        conf_dict = next(r.confidence for r in results_dict if r.rule_id == "identity_fragmentation")

        assert conf_obj == conf_dict
        assert conf_obj == 55  # 75 base - 20 (avg 30 < 40)

    def test_detection_confidence_dict_missing_confidence_defaults_100(self, engine):
        """Dict entries without 'confidence' key should default to 100 (no dampening)."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": {
                "technologies": [
                    {"name": "GA4", "category": "analytics"},
                    {"name": "Hotjar", "category": "analytics"},
                    {"name": "Mixpanel", "category": "analytics"},
                    {"name": "GTM", "category": "tag manager"},
                ]
            }},
        )
        results = engine.evaluate(bundle)
        r = next(r for r in results if r.rule_id == "identity_fragmentation")
        assert r.confidence == 75  # No dampening

    def test_detection_confidence_dict_ignores_malformed_entries(self, engine):
        """Dict entries without 'name' should be silently skipped."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": {
                "technologies": [
                    {"name": "GA4", "category": "analytics", "confidence": 30},
                    {"category": "analytics", "confidence": 30},  # No name
                    {"name": "Hotjar", "category": "analytics", "confidence": 30},
                    {"name": "Mixpanel", "category": "analytics", "confidence": 30},
                    {"name": "GTM", "category": "tag manager", "confidence": 30},
                ]
            }},
        )
        results = engine.evaluate(bundle)
        r = next(r for r in results if r.rule_id == "identity_fragmentation")
        assert r.confidence == 55  # Still dampened based on named entries


class TestDataInfraPainBehaviorLock:
    def test_single_data_role_triggers(self, engine):
        """A single 'data' role type is sufficient to fire data_infra_pain."""
        bundle = SignalBundle(
            job_signals=JobSignals(
                role_types=["data"],
                seniority_distribution={"mid": 1},
                tech_mentions=[],
            ),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "data_infra_pain" in ids
        r = next(r for r in results if r.rule_id == "data_infra_pain")
        assert r.confidence == 50
        assert r.category == "data"

    def test_no_data_role_does_not_trigger(self, engine):
        """Without a 'data' role type, data_infra_pain does not fire."""
        bundle = SignalBundle(
            job_signals=JobSignals(
                role_types=["backend", "frontend"],
                seniority_distribution={"senior": 3},
                tech_mentions=[],
            ),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "data_infra_pain" not in ids

    def test_no_job_signals_does_not_trigger(self, engine):
        """No job_signals at all → no fire."""
        bundle = SignalBundle()
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "data_infra_pain" not in ids


# --- Frontend rule kill switch ---


class TestFrontendRuleKillSwitch:
    def test_flag_off_no_frontend_inference(self, engine):
        """With pain_frontend_rule_enabled=False (default), frontend_performance_debt never fires."""
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("React", "javascript framework"), ("Vue", "javascript framework"),
                ("jQuery", "javascript framework"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "frontend_performance_debt" not in ids

    @patch("services.pain_inference.get_settings")
    def test_flag_on_emits_frontend_inference(self, mock_settings, engine):
        """With pain_frontend_rule_enabled=True, frontend_performance_debt fires normally."""
        mock_settings.return_value = MagicMock(pain_frontend_rule_enabled=True)
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("React", "javascript framework"), ("Vue", "javascript framework"),
                ("jQuery", "javascript framework"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "frontend_performance_debt" in ids


# --- detect_seller_category ---


class TestDetectSellerCategory:
    def test_detects_database(self):
        assert detect_seller_category("MongoDB Atlas - scalable database platform") == "database"

    def test_returns_empty_for_crm(self):
        assert detect_seller_category("Salesforce CRM for enterprise sales") == ""

    def test_returns_empty_for_empty_input(self):
        assert detect_seller_category("") == ""

    def test_requires_two_hits(self):
        """Single keyword match should not trigger category detection."""
        assert detect_seller_category("We help with database things") == ""


# --- is_action_tier_relevant ---


class TestIsActionTierRelevant:
    def test_clean_signal_passes(self):
        """Signals not in denied families pass through."""
        inference = PainInference(
            rule_id="database_scaling_pressure",
            title="Database Scaling Pressure",
            description="Single DB with hiring pressure.",
            severity="medium",
            evidence=["Single database: postgresql"],
            confidence=55,
            category="engineering",
        )
        assert is_action_tier_relevant(inference, "database") is True

    def test_frontend_signal_blocked_for_db_seller(self):
        """Frontend signals are blocked for database sellers."""
        inference = PainInference(
            rule_id="frontend_performance_debt",
            title="Frontend Performance Debt",
            description="Multiple JS frameworks without a CDN.",
            severity="medium",
            evidence=["Frameworks: React, Vue", "No CDN detected"],
            confidence=50,
            category="engineering",
        )
        assert is_action_tier_relevant(inference, "database") is False

    def test_frontend_signal_with_db_linkage_passes(self):
        """Frontend signal with explicit DB linkage overrides the block."""
        inference = PainInference(
            rule_id="frontend_performance_debt",
            title="Frontend Performance Debt",
            description="Multiple JS frameworks causing database bottleneck in API layer.",
            severity="medium",
            evidence=["Frameworks: React, Vue", "API latency traced to query performance"],
            confidence=50,
            category="engineering",
        )
        assert is_action_tier_relevant(inference, "database") is True

    def test_unknown_category_passes(self):
        """Unknown seller category always passes."""
        inference = PainInference(
            rule_id="frontend_performance_debt",
            title="Frontend Performance Debt",
            description="Multiple JS frameworks without a CDN.",
            severity="medium",
            evidence=["Frameworks: React, Vue"],
            confidence=50,
            category="engineering",
        )
        assert is_action_tier_relevant(inference, "unknown_cat") is True

    def test_empty_category_passes(self):
        """Empty seller category always passes."""
        inference = PainInference(
            rule_id="frontend_performance_debt",
            title="Frontend Performance Debt",
            description="Multiple JS frameworks without a CDN.",
            severity="medium",
            evidence=["Frameworks: React, Vue"],
            confidence=50,
            category="engineering",
        )
        assert is_action_tier_relevant(inference, "") is True

    def test_tag_bloat_blocked_for_db_seller(self):
        """Marketing tag bloat is blocked for database sellers."""
        inference = PainInference(
            rule_id="tag_bloat",
            title="Tag/Analytics Bloat",
            description="6+ analytics tools detected.",
            severity="medium",
            evidence=["Detected 8 analytics/ad/tag tools"],
            confidence=60,
            category="marketing",
        )
        assert is_action_tier_relevant(inference, "database") is False



# --- Action Tier gate in evaluate() ---


class TestActionTierGateInEvaluate:
    @patch("services.pain_inference.get_settings")
    def test_frontend_signal_demoted_to_background_for_db_seller(self, mock_settings, engine):
        """When seller is DB, frontend_performance_debt gets _background_ prefix."""
        mock_settings.return_value = MagicMock(pain_frontend_rule_enabled=True)
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("React", "javascript framework"), ("Vue", "javascript framework"),
                ("jQuery", "javascript framework"),
            )},
        )
        results = engine.evaluate(bundle, seller_product_context="MongoDB Atlas - scalable database platform")
        frontend = [r for r in results if r.rule_id == "frontend_performance_debt"]
        assert len(frontend) == 1
        assert frontend[0].category.startswith("_background_")

    @patch("services.pain_inference.get_settings")
    def test_db_signal_not_demoted_for_db_seller(self, mock_settings, engine):
        """Database scaling pressure stays in normal category for DB seller."""
        mock_settings.return_value = MagicMock(pain_frontend_rule_enabled=False)
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(("postgresql", "database"),)},
            job_signals=JobSignals(role_types=["data", "backend"], tech_mentions=[], seniority_distribution={}),
        )
        results = engine.evaluate(bundle, seller_product_context="MongoDB Atlas - scalable database platform")
        db_signals = [r for r in results if r.rule_id == "database_scaling_pressure"]
        assert len(db_signals) == 1
        assert not db_signals[0].category.startswith("_background_")


# --- Golden fixture: Nike/Costco-like tech profile ---


class TestGoldenFixtureDbSeller:
    """Nike/Costco-like tech profile should not produce frontend debt in Action Tier for DB seller."""

    @patch("services.pain_inference.get_settings")
    def test_large_retail_tech_profile_no_frontend_in_action_tier(self, mock_settings, engine):
        mock_settings.return_value = MagicMock(pain_frontend_rule_enabled=True)
        bundle = SignalBundle(
            tech_by_domain={
                "www.bigretail.com": _make_stack(
                    ("React", "javascript framework"),
                    ("jQuery", "javascript"),
                    ("Bootstrap", "css framework"),
                    ("Google Analytics", "analytics"),
                    ("Hotjar", "analytics"),
                    ("GTM", "tag manager"),
                    ("Optimizely", "analytics"),
                ),
                "app.bigretail.com": _make_stack(
                    ("Angular", "javascript framework"),
                    ("Node.js", "javascript"),
                    ("PostgreSQL", "database"),
                ),
            },
            job_signals=JobSignals(
                role_types=["frontend", "backend", "data"],
                tech_mentions=[
                    TechMention(name="React", category="javascript", count=3),
                    TechMention(name="PostgreSQL", category="database", count=2),
                ],
                seniority_distribution={"senior": 2, "mid": 3},
            ),
        )
        results = engine.evaluate(
            bundle,
            seller_product_context="MongoDB Atlas - scalable database platform for modern applications",
        )

        # Frontend signals should be background-only
        for r in results:
            if r.rule_id in ("frontend_performance_debt", "tag_bloat", "marketing_product_mismatch"):
                assert r.category.startswith("_background_"), \
                    f"{r.rule_id} should be background-only for DB seller, got category={r.category}"

        # Database/data signals should NOT be background
        for r in results:
            if r.rule_id in ("database_scaling_pressure", "data_infra_pain"):
                assert not r.category.startswith("_background_"), \
                    f"{r.rule_id} should be action-tier for DB seller, got category={r.category}"
