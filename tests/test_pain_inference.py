"""Tests for services/pain_inference.py"""

import pytest
from services.pain_inference import PainInferenceEngine
from models import (
    SignalBundle, DNSProfile, SSLProfile, SecurityPosture,
    RobotsSignals, JobSignals, TechMention, TechStack, DetectedTechnology,
)


@pytest.fixture
def engine():
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
    def test_triggers_missing_spf(self, engine):
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dkim=True, has_dmarc=True, dmarc_policy="reject"),
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "email_risk" in ids

    def test_no_trigger_all_present(self, engine):
        bundle = SignalBundle(
            dns_profile=DNSProfile(domain="x.com", has_spf=True, has_dkim=True, has_dmarc=True, dmarc_policy="reject"),
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
    def test_triggers(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("React", "javascript framework"), ("Vue", "javascript framework"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "frontend_performance_debt" in ids

    def test_no_trigger_with_cdn(self, engine):
        bundle = SignalBundle(
            tech_by_domain={"x.com": _make_stack(
                ("React", "javascript framework"), ("Vue", "javascript framework"),
                ("Cloudflare", "cdn"),
            )},
        )
        results = engine.evaluate(bundle)
        ids = [r.rule_id for r in results]
        assert "frontend_performance_debt" not in ids

    def test_no_trigger_meta_framework_pair(self, engine):
        """Next.js + React should not fire since Next.js wraps React."""
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
        assert r.confidence == 40
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
        """APM tool detected = no fire."""
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

    def test_no_trigger_with_devops_monitoring_mention(self, engine):
        """Monitoring mentioned in job signals devops category = no fire."""
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
        assert "email_risk" in ids
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
    def test_observability_gap_dampened_by_devops_hiring(self, engine):
        bundle = SignalBundle(
            tech_by_domain={
                "app.example.com": _make_stack(("React", "javascript framework"),),
            },
            job_signals=JobSignals(role_types=["devops"], tech_mentions=[]),
        )
        results = engine.evaluate(bundle)
        r = next((r for r in results if r.rule_id == "observability_gap"), None)
        assert r is not None
        assert r.confidence == 30  # 40 - 10

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
            dns_profile=DNSProfile(domain="x.com", has_spf=False, has_dkim=False, has_dmarc=False),
        )
        results = engine.evaluate(bundle)
        email = next(r for r in results if r.rule_id == "email_risk")
        assert email.category == "security"


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
