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
