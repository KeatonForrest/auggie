"""Tests for services/techdetect/archetypes.py — stack archetype detection."""

import pytest
from services.techdetect.archetypes import detect_archetypes


class TestModernSPA:
    def test_react_only(self):
        results = detect_archetypes({"React"})
        names = [r["name"] for r in results]
        assert "Modern SPA" in names

    def test_react_with_supporting(self):
        results = detect_archetypes({"React", "webpack", "Redux", "TypeScript"})
        spa = next(r for r in results if r["name"] == "Modern SPA")
        assert spa["confidence"] > 0.6
        assert "React" in spa["matched_technologies"]

    def test_vue(self):
        results = detect_archetypes({"Vue.js", "Vuex"})
        spa = next(r for r in results if r["name"] == "Modern SPA")
        assert spa["confidence"] > 0.6

    def test_angular(self):
        results = detect_archetypes({"Angular"})
        names = [r["name"] for r in results]
        assert "Modern SPA" in names


class TestJAMstack:
    def test_nextjs(self):
        results = detect_archetypes({"Next.js"})
        names = [r["name"] for r in results]
        assert "JAMstack/SSR" in names

    def test_gatsby_with_supporting(self):
        results = detect_archetypes({"Gatsby", "Netlify", "Contentful", "GraphQL"})
        jam = next(r for r in results if r["name"] == "JAMstack/SSR")
        assert jam["confidence"] > 0.8


class TestWordPress:
    def test_wordpress_basic(self):
        results = detect_archetypes({"WordPress"})
        names = [r["name"] for r in results]
        assert "WordPress Stack" in names

    def test_wordpress_full(self):
        results = detect_archetypes({"WordPress", "PHP", "MySQL", "WooCommerce", "Yoast SEO"})
        wp = next(r for r in results if r["name"] == "WordPress Stack")
        assert wp["confidence"] > 0.9


class TestEnterpriseCMS:
    def test_sitecore(self):
        results = detect_archetypes({"Sitecore"})
        names = [r["name"] for r in results]
        assert "Enterprise CMS" in names

    def test_drupal(self):
        results = detect_archetypes({"Drupal"})
        names = [r["name"] for r in results]
        assert "Enterprise CMS" in names


class TestEcommerce:
    def test_shopify(self):
        results = detect_archetypes({"Shopify"})
        names = [r["name"] for r in results]
        assert "E-commerce Platform" in names

    def test_magento_with_stripe(self):
        results = detect_archetypes({"Magento", "Stripe", "Google Tag Manager"})
        ecom = next(r for r in results if r["name"] == "E-commerce Platform")
        assert ecom["confidence"] > 0.7


class TestLAMPLEMP:
    def test_php_apache(self):
        results = detect_archetypes({"PHP", "Apache"})
        names = [r["name"] for r in results]
        assert "LAMP/LEMP" in names

    def test_php_nginx_mysql(self):
        results = detect_archetypes({"PHP", "Nginx", "MySQL", "Laravel"})
        lamp = next(r for r in results if r["name"] == "LAMP/LEMP")
        assert lamp["confidence"] > 0.7


class TestNodeBackend:
    def test_nodejs(self):
        results = detect_archetypes({"Node.js"})
        names = [r["name"] for r in results]
        assert "Node.js Backend" in names

    def test_express_full(self):
        results = detect_archetypes({"Express", "MongoDB", "Redis", "TypeScript"})
        node = next(r for r in results if r["name"] == "Node.js Backend")
        assert node["confidence"] > 0.7


class TestPythonBackend:
    def test_django(self):
        results = detect_archetypes({"Django"})
        names = [r["name"] for r in results]
        assert "Python Backend" in names

    def test_flask(self):
        results = detect_archetypes({"Flask"})
        names = [r["name"] for r in results]
        assert "Python Backend" in names


class TestJavaEnterprise:
    def test_java(self):
        results = detect_archetypes({"Java"})
        names = [r["name"] for r in results]
        assert "Java Enterprise" in names

    def test_java_spring(self):
        results = detect_archetypes({"Java", "Spring Boot", "Oracle"})
        java = next(r for r in results if r["name"] == "Java Enterprise")
        assert java["confidence"] > 0.7


class TestDotNet:
    def test_aspnet(self):
        results = detect_archetypes({"ASP.NET"})
        names = [r["name"] for r in results]
        assert ".NET Stack" in names

    def test_dotnet_iis(self):
        results = detect_archetypes({".NET", "IIS", "Microsoft SQL Server"})
        dotnet = next(r for r in results if r["name"] == ".NET Stack")
        assert dotnet["confidence"] > 0.7


class TestServerless:
    def test_vercel(self):
        results = detect_archetypes({"Vercel"})
        names = [r["name"] for r in results]
        assert "Serverless/Edge" in names

    def test_cloudflare_workers(self):
        results = detect_archetypes({"Cloudflare Workers", "Supabase", "TypeScript"})
        sless = next(r for r in results if r["name"] == "Serverless/Edge")
        assert sless["confidence"] > 0.7


class TestEdgeCases:
    def test_empty_input(self):
        results = detect_archetypes(set())
        assert results == []

    def test_no_match(self):
        results = detect_archetypes({"SomeObscureTech", "AnotherRandomLib"})
        assert results == []

    def test_case_insensitivity(self):
        results = detect_archetypes({"react"})
        names = [r["name"] for r in results]
        assert "Modern SPA" in names

    def test_multiple_archetypes(self):
        results = detect_archetypes({"WordPress", "PHP", "Nginx", "MySQL", "React"})
        names = [r["name"] for r in results]
        assert "WordPress Stack" in names
        assert "LAMP/LEMP" in names
        assert "Modern SPA" in names

    def test_sorted_by_confidence_descending(self):
        results = detect_archetypes({"WordPress", "PHP", "MySQL", "Nginx", "React", "webpack"})
        confidences = [r["confidence"] for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_matched_technologies_populated(self):
        results = detect_archetypes({"React", "webpack"})
        spa = next(r for r in results if r["name"] == "Modern SPA")
        assert "React" in spa["matched_technologies"]
        assert "webpack" in spa["matched_technologies"]

    def test_description_present(self):
        results = detect_archetypes({"React"})
        spa = next(r for r in results if r["name"] == "Modern SPA")
        assert spa["description"]
        assert isinstance(spa["description"], str)
