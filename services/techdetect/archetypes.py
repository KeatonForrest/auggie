"""Stack archetype detection — identifies composite technology patterns."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ArchetypeRule:
    """Defines a stack archetype.

    required: list of OR-groups (sets). ALL groups must have at least one match.
    supporting: list of OR-groups. Each matched group boosts confidence.
    description: human-readable summary of what this archetype signals.
    """
    name: str
    required: tuple[frozenset[str], ...] = ()
    supporting: tuple[frozenset[str], ...] = ()
    description: str = ""


def _fs(*items: str) -> frozenset[str]:
    """Shorthand for frozenset with lowered items."""
    return frozenset(s.lower() for s in items)


ARCHETYPES: tuple[ArchetypeRule, ...] = (
    ArchetypeRule(
        name="Modern SPA",
        required=(
            _fs("React", "Vue.js", "Angular", "Svelte"),
        ),
        supporting=(
            _fs("webpack", "Vite", "esbuild", "Parcel"),
            _fs("Redux", "MobX", "Vuex", "Pinia", "NgRx"),
            _fs("TypeScript"),
            _fs("Next.js", "Nuxt.js", "Gatsby", "SvelteKit"),
        ),
        description="Single-page application with modern JS framework",
    ),
    ArchetypeRule(
        name="JAMstack/SSR",
        required=(
            _fs("Next.js", "Nuxt.js", "Gatsby", "Astro", "SvelteKit", "Remix"),
        ),
        supporting=(
            _fs("Vercel", "Netlify", "Cloudflare"),
            _fs("GraphQL", "Apollo"),
            _fs("Contentful", "Sanity", "Strapi", "Prismic"),
            _fs("TypeScript"),
        ),
        description="Server-rendered or static-generated JAMstack site",
    ),
    ArchetypeRule(
        name="WordPress Stack",
        required=(
            _fs("WordPress"),
        ),
        supporting=(
            _fs("PHP"),
            _fs("MySQL"),
            _fs("WooCommerce"),
            _fs("Yoast SEO"),
            _fs("Elementor", "WPBakery"),
        ),
        description="WordPress-based content management",
    ),
    ArchetypeRule(
        name="Enterprise CMS",
        required=(
            _fs("Adobe Experience Manager", "Sitecore", "Episerver",
                "Optimizely", "Kentico", "Acquia", "Drupal"),
        ),
        supporting=(
            _fs("Java"),
            _fs(".NET", "ASP.NET"),
            _fs("Akamai", "Fastly", "CloudFront"),
            _fs("Adobe Analytics", "Adobe Target"),
        ),
        description="Enterprise-grade content management system",
    ),
    ArchetypeRule(
        name="E-commerce Platform",
        required=(
            _fs("Shopify", "Magento", "WooCommerce", "BigCommerce",
                "Salesforce Commerce Cloud", "PrestaShop", "OpenCart"),
        ),
        supporting=(
            _fs("Stripe", "PayPal", "Braintree", "Adyen"),
            _fs("Google Analytics", "Google Tag Manager"),
            _fs("Klaviyo", "Mailchimp"),
            _fs("Cloudflare", "Fastly", "Akamai"),
        ),
        description="Dedicated e-commerce platform",
    ),
    ArchetypeRule(
        name="LAMP/LEMP",
        required=(
            _fs("PHP"),
            _fs("Apache", "Nginx"),
        ),
        supporting=(
            _fs("MySQL", "MariaDB"),
            _fs("Laravel", "Symfony", "CodeIgniter", "CakePHP"),
            _fs("Linux"),
            _fs("Redis", "Memcached"),
        ),
        description="Classic Linux/Apache(Nginx)/MySQL/PHP stack",
    ),
    ArchetypeRule(
        name="Node.js Backend",
        required=(
            _fs("Node.js", "Express"),
        ),
        supporting=(
            _fs("MongoDB", "PostgreSQL"),
            _fs("Redis"),
            _fs("TypeScript"),
            _fs("Docker"),
            _fs("GraphQL", "Apollo"),
        ),
        description="Node.js/Express server-side application",
    ),
    ArchetypeRule(
        name="Python Backend",
        required=(
            _fs("Python", "Django", "Flask", "FastAPI"),
        ),
        supporting=(
            _fs("PostgreSQL", "MySQL"),
            _fs("Redis", "Celery"),
            _fs("Nginx", "Gunicorn", "uWSGI"),
            _fs("Docker"),
        ),
        description="Python-based web application backend",
    ),
    ArchetypeRule(
        name="Java Enterprise",
        required=(
            _fs("Java"),
        ),
        supporting=(
            _fs("Spring", "Spring Boot"),
            _fs("Apache Tomcat", "JBoss", "WildFly", "WebLogic", "WebSphere"),
            _fs("Oracle", "PostgreSQL"),
            _fs("Docker", "Kubernetes"),
        ),
        description="Java-based enterprise application",
    ),
    ArchetypeRule(
        name=".NET Stack",
        required=(
            _fs("ASP.NET", ".NET", "Microsoft ASP.NET"),
        ),
        supporting=(
            _fs("IIS"),
            _fs("Microsoft SQL Server", "Azure"),
            _fs("Angular", "React", "Blazor"),
            _fs("Docker"),
        ),
        description="Microsoft .NET web application stack",
    ),
    ArchetypeRule(
        name="Serverless/Edge",
        required=(
            _fs("Vercel", "Netlify", "Cloudflare Workers",
                "AWS Lambda", "Google Cloud Functions", "Azure Functions"),
        ),
        supporting=(
            _fs("Next.js", "Nuxt.js", "Remix", "Astro"),
            _fs("DynamoDB", "FaunaDB", "PlanetScale", "Supabase"),
            _fs("Stripe"),
            _fs("TypeScript"),
        ),
        description="Serverless or edge-deployed application",
    ),
)


def detect_archetypes(tech_names: set[str]) -> list[dict]:
    """Detect stack archetypes from a set of technology names.

    Returns list of dicts sorted by confidence descending:
        [{"name": ..., "confidence": ..., "matched_technologies": [...], "description": ...}]
    """
    if not tech_names:
        return []

    lower_names = {n.lower() for n in tech_names}
    results = []

    for rule in ARCHETYPES:
        # Check all required groups — each must have at least one match
        required_met = True
        matched_techs = set()
        for group in rule.required:
            matches = group & lower_names
            if not matches:
                required_met = False
                break
            matched_techs.update(matches)

        if not required_met:
            continue

        # Base confidence for meeting all required groups
        confidence = 0.6

        # Boost from supporting groups
        supporting_count = len(rule.supporting)
        if supporting_count > 0:
            matched_supporting = 0
            for group in rule.supporting:
                matches = group & lower_names
                if matches:
                    matched_supporting += 1
                    matched_techs.update(matches)
            confidence += 0.4 * (matched_supporting / supporting_count)

        # Map back to original-case names
        original_matched = [n for n in tech_names if n.lower() in matched_techs]

        results.append({
            "name": rule.name,
            "confidence": round(confidence, 2),
            "matched_technologies": sorted(original_matched),
            "description": rule.description,
        })

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results
