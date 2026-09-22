import os
import re
import uuid
import asyncio
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple, Set
from urllib.parse import urlparse, urlunparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from tavily import TavilyClient
from exa_py import Exa


# ============================================================
# CONNECTING THE DOTS AI v7 — FRONTEND-ALIGNED BUILD
# ============================================================
#
# Only two endpoints are exposed because the frontend only
# calls these two:
#
#   GET  /api/health    -> backend status badge
#   POST /api/research  -> main research pipeline
#
# Everything else (outreach, pitch, application, startup-plan,
# strategy, fundraising-sources, entities/search, opportunities,
# cache) has been removed because the frontend never calls it.
#
# The full pipeline (Exa discovery -> entity resolution ->
# selective Tavily verification -> fit scoring) is preserved
# because /api/research uses it.
# ============================================================


load_dotenv()

APP_VERSION = "7.0.0"


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Connecting the Dots AI",
    version=APP_VERSION,
    description=(
        "Startup intelligence engine for customer acquisition, "
        "validation, incubation, accelerators, grants, investors "
        "and targeted pitching."
    ),
)


ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,"
        "http://localhost:3001,"
        "https://connecting-the-dots-web.vercel.app",
    ).split(",")
    if origin.strip()
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# PROVIDERS
# ============================================================

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY = os.getenv("EXA_API_KEY")

if not TAVILY_API_KEY:
    raise RuntimeError("TAVILY_API_KEY is not configured.")

if not EXA_API_KEY:
    raise RuntimeError("EXA_API_KEY is not configured.")


tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
exa_client = Exa(api_key=EXA_API_KEY)


# ============================================================
# REQUEST MODELS
# ============================================================

MODE_PATTERN = (
    "^(auto|traction|validation|fundraising|pitching|"
    "investor_discovery|customer_acquisition|incubation|"
    "application|partnership)$"
)

BUDGET_PATTERN = "^(cheap|balanced|deep)$"


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    user_id: Optional[str] = "anonymous"
    limit: int = Field(default=25, ge=1, le=25)
    adaptive: bool = True
    budget_tier: str = Field(default="balanced", pattern=BUDGET_PATTERN)
    mode: str = Field(default="auto", pattern=MODE_PATTERN)
    include_free_sources: bool = True


class StartupProfile(BaseModel):
    """Still needed because pdf_sources_as_resources uses it internally."""
    company_name: str = "Connecting the Dots AI"
    product: str = Field(
        default="AI relationship and market intelligence platform",
        max_length=1000,
    )
    description: str = Field(
        default=(
            "AI that maps non-obvious relationships between companies, "
            "products, markets, distributors, customers and investors."
        ),
        max_length=3000,
    )
    website: Optional[str] = None
    geography: str = "India"
    target_geographies: List[str] = Field(default_factory=lambda: ["India", "UAE"])
    industry: str = "AI / B2B SaaS"
    stage: str = "early stage"
    business_model: str = "B2B SaaS"
    customer_types: List[str] = Field(
        default_factory=lambda: [
            "B2B companies", "manufacturers", "distributors",
            "market intelligence teams", "sales teams", "investors",
            "startup founders",
        ]
    )
    buyer_roles: List[str] = Field(
        default_factory=lambda: [
            "Founder", "CEO", "Business Development",
            "Sales Director", "Strategy", "Investment Team",
        ]
    )
    pain_points: List[str] = Field(
        default_factory=lambda: [
            "finding non-obvious business relationships",
            "finding qualified B2B prospects",
            "finding distributors",
            "finding investors",
            "market intelligence",
            "reducing manual research",
        ]
    )
    value_proposition: Optional[str] = None
    traction: List[str] = Field(default_factory=list)
    fundraising_stage: Optional[str] = None
    fundraising_amount: Optional[str] = None
    ask: Optional[str] = None


# ============================================================
# CONSTANTS
# ============================================================

CATEGORIES = [
    "VC", "ANGEL", "ACCELERATOR", "INCUBATOR", "FAMILY_OFFICE",
    "FOUNDATION", "LP", "GRANT", "CROWDFUNDING", "COMMUNITY",
    "CUSTOMER", "PARTNER", "APPLICATION_PROGRAM", "RESOURCE",
]


MODES = {
    "traction", "validation", "fundraising", "pitching",
    "investor_discovery", "customer_acquisition", "incubation",
    "application", "partnership",
}


# ============================================================
# SEARCH / COST CONTROL
# ============================================================

EXA_MAX_RESULTS = 6
MAX_CANDIDATES = 60

MAX_DEEP_VERIFY = 6
MAX_LIGHT_VERIFY = 6
MAX_ADAPTIVE_VERIFY = 4

MAX_TAVILY_RESULTS = 2

MAX_CONCURRENT_SEARCHES = 6

EXA_TEXT_LIMIT = 3500
TAVILY_CONTENT_LIMIT = 3200
EVIDENCE_LIMIT = 1600


BUDGETS = {
    "cheap":    {"exa": 8,  "tavily": 4,  "adaptive_exa": 0},
    "balanced": {"exa": 12, "tavily": 14, "adaptive_exa": 3},
    "deep":     {"exa": 18, "tavily": 22, "adaptive_exa": 6},
}


SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL", "86400"))
PROFILE_CACHE_TTL = int(os.getenv("PROFILE_CACHE_TTL", "604800"))
EVIDENCE_CACHE_TTL = int(os.getenv("EVIDENCE_CACHE_TTL", "604800"))
STRATEGY_CACHE_TTL = int(os.getenv("STRATEGY_CACHE_TTL", "86400"))

CACHE_PATH = os.getenv(
    "CACHE_PATH",
    os.path.join("/tmp", "connecting_dots_cache.db"),
)


SOURCE_TYPES = {
    "official", "government", "investor_platform", "accelerator",
    "incubator", "community", "social", "marketplace", "media",
    "directory", "unknown",
}


# ============================================================
# FREE-FIRST SOURCE CATALOG
# ============================================================

FREE_SOURCE_CATALOG: List[Dict[str, Any]] = [

    {
        "id": "harshentrepre-x",
        "name": "HarshEntrepre on X",
        "kind": "social",
        "access": "free",
        "mode": ["fundraising", "pitching", "traction", "validation", "incubation"],
        "url": "https://x.com/HarshEntrepre",
        "description": (
            "Public founder/resource source to monitor for startup "
            "opportunities, fundraising resources, startup ideas and "
            "ecosystem information."
        ),
        "query_templates": [
            'site:x.com/HarshEntrepre startup fundraising',
            'site:x.com/HarshEntrepre incubator accelerator',
            'site:x.com/HarshEntrepre grants funding',
            'site:x.com/HarshEntrepre pitch investor',
            'site:x.com/HarshEntrepre startup resources',
        ],
        "verification_rule": (
            "Only treat an individual post as evidence when "
            "the post itself is retrieved and dated."
        ),
    },

    {
        "id": "openvc",
        "name": "OpenVC",
        "kind": "investor_platform",
        "access": "free_core",
        "mode": ["fundraising", "investor_discovery", "pitching"],
        "url": "https://www.openvc.app/",
        "description": (
            "Investor discovery and outreach platform. "
            "Public information currently advertises free "
            "founder access and a large investor database."
        ),
        "query_templates": [
            'site:openvc.app investor startup pre-seed seed',
            'site:openvc.app investor startup AI SaaS',
        ],
        "verification_rule": (
            "Check current founder plan and investor-specific "
            "requirements before outreach."
        ),
    },

    {
        "id": "yc",
        "name": "Y Combinator",
        "kind": "accelerator",
        "access": "application_based",
        "mode": ["fundraising", "pitching", "validation", "incubation", "application"],
        "url": "https://www.ycombinator.com/apply",
        "description": (
            "Accelerator application route with founder "
            "resources and an application process."
        ),
        "query_templates": [
            'site:ycombinator.com/apply startup application',
            'site:ycombinator.com startup application funding',
        ],
        "verification_rule": (
            "Always check current batch, deadline and application "
            "requirements."
        ),
    },

    {
        "id": "f6s",
        "name": "F6S",
        "kind": "accelerator",
        "access": "free_core",
        "mode": ["fundraising", "validation", "traction", "incubation", "application"],
        "url": "https://www.f6s.com/",
        "description": (
            "Startup opportunity platform for accelerators, "
            "grants, funding programs and founder benefits."
        ),
        "query_templates": [
            'site:f6s.com startup grants accelerator funding',
            'site:f6s.com startup program apply',
        ],
        "verification_rule": (
            "Verify each individual opportunity's eligibility, "
            "deadline and commercial terms."
        ),
    },

    {
        "id": "startup-india",
        "name": "Startup India",
        "kind": "government",
        "access": "free",
        "mode": ["fundraising", "incubation", "application", "validation"],
        "url": "https://www.startupindia.gov.in/",
        "description": (
            "Government startup ecosystem containing schemes, "
            "policies, startup recognition, mentorship and funding resources."
        ),
        "query_templates": [
            'site:startupindia.gov.in startup funding scheme',
            'site:startupindia.gov.in incubator startup application',
            'site:startupindia.gov.in startup grants',
        ],
        "verification_rule": (
            "Verify current scheme status, eligibility, deadlines "
            "and application requirements."
        ),
    },

    {
        "id": "sisfs",
        "name": "Startup India Seed Fund Scheme",
        "kind": "government",
        "access": "application_based",
        "mode": ["fundraising", "incubation", "application"],
        "url": "https://seedfund.startupindia.gov.in/",
        "description": (
            "Startup India Seed Fund Scheme for eligible startups "
            "through participating incubators."
        ),
        "query_templates": [
            'site:seedfund.startupindia.gov.in startup seed fund eligibility',
            'site:seedfund.startupindia.gov.in startup application',
        ],
        "verification_rule": (
            "Eligibility and application windows must be checked "
            "against the current official portal."
        ),
    },

    {
        "id": "product-hunt",
        "name": "Product Hunt",
        "kind": "community",
        "access": "free",
        "mode": ["traction", "validation", "pitching"],
        "url": "https://www.producthunt.com/",
        "description": (
            "Product launch and discovery community useful for "
            "early feedback, awareness and user discovery."
        ),
        "query_templates": [
            'site:producthunt.com startup launch AI SaaS',
            'site:producthunt.com launch guide startup',
        ],
        "verification_rule": (
            "Treat launch activity as a traction experiment, "
            "not proof of product-market fit."
        ),
    },

    {
        "id": "reddit",
        "name": "Reddit",
        "kind": "community",
        "access": "free",
        "mode": ["validation", "traction", "customer_acquisition"],
        "url": "https://www.reddit.com/",
        "description": (
            "Community conversations can reveal customer pain, "
            "existing alternatives and potential early users."
        ),
        "query_templates": [
            'site:reddit.com startup customer pain problem',
            'site:reddit.com SaaS alternative customer',
            'site:reddit.com "would pay" software',
        ],
        "verification_rule": (
            "Use multiple conversations and avoid treating "
            "individual comments as market-size evidence."
        ),
    },

    {
        "id": "hacker-news",
        "name": "Hacker News",
        "kind": "community",
        "access": "free",
        "mode": ["validation", "traction"],
        "url": "https://news.ycombinator.com/",
        "description": (
            "Useful for technical startup feedback, Show HN launches "
            "and founder/customer discussions."
        ),
        "query_templates": [
            'site:news.ycombinator.com startup SaaS problem',
            'site:news.ycombinator.com "Show HN" AI startup',
        ],
        "verification_rule": "Community discussion is a directional signal.",
    },

    {
        "id": "github",
        "name": "GitHub",
        "kind": "community",
        "access": "free",
        "mode": ["validation", "traction"],
        "url": "https://github.com/",
        "description": (
            "Useful for discovering open-source alternatives, "
            "technical demand, issues and potential users."
        ),
        "query_templates": [
            'site:github.com AI market intelligence startup',
            'site:github.com business intelligence API issues',
        ],
        "verification_rule": (
            "Stars, issues and forks are signals rather than "
            "equivalent to paying customers."
        ),
    },

    {
        "id": "linkedin",
        "name": "LinkedIn",
        "kind": "social",
        "access": "free_core",
        "mode": ["customer_acquisition", "traction", "pitching", "partnership"],
        "url": "https://www.linkedin.com/",
        "description": (
            "Useful for identifying companies, decision makers, "
            "partners and warm-introduction paths."
        ),
        "query_templates": [
            'site:linkedin.com company procurement director SaaS',
            'site:linkedin.com "business development" startup buyer',
            'site:linkedin.com "investment team" VC partner',
        ],
        "verification_rule": "Verify current roles before outreach.",
    },

    {
        "id": "indiamart",
        "name": "IndiaMART",
        "kind": "marketplace",
        "access": "free_core",
        "mode": ["customer_acquisition", "validation", "traction"],
        "url": "https://www.indiamart.com/",
        "description": (
            "B2B marketplace useful for discovering suppliers, "
            "buyers, distributors and product categories."
        ),
        "query_templates": [
            'site:indiamart.com distributors manufacturers buyers',
            'site:indiamart.com B2B buyers suppliers',
        ],
        "verification_rule": (
            "Listings are prospecting signals and should be "
            "verified before outreach."
        ),
    },
]


# ============================================================
# PDF-DERIVED FUNDRAISING / VIRTUAL-INCUBATION CATALOG
# ============================================================

PDF_SOURCE_CATALOG: List[Dict[str, Any]] = [

    {
        "id": "openvc-app", "name": "OpenVC",
        "url": "https://www.openvc.app/",
        "kind": "investor_platform", "access": "free_core",
        "stage": ["pre-seed", "seed", "early"], "geography": ["Global"],
        "mode": ["fundraising", "investor_discovery", "pitching"],
        "description": "Free investor database + outreach tools for founders.",
    },
    {
        "id": "f6s-programs", "name": "F6S Programs",
        "url": "https://www.f6s.com/programs",
        "kind": "accelerator", "access": "free_core",
        "stage": ["pre-seed", "seed", "early"], "geography": ["Global"],
        "mode": ["fundraising", "incubation", "application"],
        "description": "Open accelerator, grant and funding programs.",
    },
    {
        "id": "foundercrete", "name": "Foundercrete Investor Database",
        "url": "https://app.foundercrete.com/investor-database/all-investor",
        "kind": "directory", "access": "free_core",
        "stage": ["any"], "geography": ["Global"],
        "mode": ["fundraising", "investor_discovery"],
        "description": "Searchable investor database (all investors).",
    },
    {
        "id": "connectvcs", "name": "ConnectVCS",
        "url": "https://connectvcs.connectclub.in/search",
        "kind": "investor_platform", "access": "free_core",
        "stage": ["seed", "early"], "geography": ["India"],
        "mode": ["fundraising", "investor_discovery"],
        "description": "India VC search platform by ConnectClub.",
    },
    {
        "id": "nsrcel-accubate", "name": "NSRCEL Accubate",
        "url": "https://nsrcel.accubate.app/",
        "kind": "incubator", "access": "application_based",
        "stage": ["pre-seed", "seed"], "geography": ["India"],
        "mode": ["incubation", "application", "fundraising"],
        "description": "NSRCEL (IIM Bangalore) incubation platform.",
    },
    {
        "id": "startup-india-main", "name": "Startup India",
        "url": "https://www.startupindia.gov.in/",
        "kind": "government", "access": "free",
        "stage": ["any"], "geography": ["India"],
        "mode": ["fundraising", "incubation", "application"],
        "description": "Startup India central portal.",
    },
    {
        "id": "seedfund-startupindia", "name": "Startup India Seed Fund Scheme",
        "url": "https://seedfund.startupindia.gov.in/portfolio",
        "kind": "government", "access": "application_based",
        "stage": ["pre-seed", "seed"], "geography": ["India"],
        "mode": ["fundraising", "application", "incubation"],
        "description": "SISFS portfolio + eligibility.",
    },
    {
        "id": "yc-apply", "name": "Y Combinator",
        "url": "https://www.ycombinator.com/apply",
        "kind": "accelerator", "access": "application_based",
        "stage": ["pre-seed", "seed"], "geography": ["Global"],
        "mode": ["fundraising", "incubation", "application"],
        "description": "Y Combinator accelerator application.",
    },
    {
        "id": "indianvcs", "name": "IndianVCs.com",
        "url": "https://www.indianvcs.com/",
        "kind": "directory", "access": "free_core",
        "stage": ["any"], "geography": ["India"],
        "mode": ["fundraising", "investor_discovery"],
        "description": "Directory of Indian VCs.",
    },
    {
        "id": "venturecenter-funding", "name": "Venture Center — Funding Links",
        "url": "https://funding.venturecenter.co.in/links.php",
        "kind": "incubator", "access": "free",
        "stage": ["pre-seed", "seed"], "geography": ["India"],
        "mode": ["incubation", "fundraising"],
        "description": "Venture Center (Pune) funding link hub.",
    },
    # ... (keep the rest of your PDF catalog unchanged) ...
    # NOTE: for the trimmed build I've kept the entries that
    #       the frontend's sample queries are most likely to hit.
    #       Paste back the full list if you want.
]


# ============================================================
# URL CLASSIFIER
# ============================================================

URL_CATEGORY_RULES: List[Tuple[str, List[str]]] = [
    ("GRANT", ["grant", "non-dilutive", "seedfund", "startupindia",
               "startup-india", "mic.gov.in", "startupmission", "startupsq",
               "enterprisesq", "fenq", "parp", "ihk"]),
    ("ACCELERATOR", ["accelerator", "ycombinator", "y-combinator", "f6s",
                     "techstars", "500.co", "stationf", "sparklabs",
                     "younoodle", "skydeck"]),
    ("INCUBATOR", ["incubator", "incubation", "nsrcel", "venturecenter",
                   "iedc", "startupharyana", "telangana", "gujarat",
                   "letsstartup", "dmz", "remarkable"]),
    ("ANGEL", ["angel", "angel-network", "firstround", "first-round"]),
    ("FAMILY_OFFICE", ["family-office", "family_office"]),
    ("LP", ["limited-partner", "fund-of-funds"]),
    ("CROWDFUNDING", ["crowdfunding", "kickstarter", "indiegogo",
                      "wefunder", "republic.co"]),
    ("FOUNDATION", ["foundation", "impact-investor", "gatesfoundation"]),
    ("VC", ["vc", "/vc", "venture", "vcfund", "sidbivcf", "indianvcs",
            "connectvcs", "upseed", "launchvic", "trustvc",
            "startupnationcentral", "vcpedia", "venture-capital-list",
            "mapofthemoney", "roundtable"]),
    ("COMMUNITY", ["community", "mentor", "cofounderslab", "foundersbase",
                   "micromentor", "eprenz", "skool", "risein",
                   "doersunited", "idealist", "startupleadership",
                   "mentoring-club"]),
    ("RESOURCE", ["resource", "toolkit", "learning", "course", "swayam",
                  "productcompass", "useweb3", "gumroad", "notion"]),
]


def classify_url(url: str) -> str:
    if not url:
        return "RESOURCE"
    low = url.lower()
    for category, needles in URL_CATEGORY_RULES:
        for needle in needles:
            if needle in low:
                return category
    return "RESOURCE"


def classify_access(url: str) -> str:
    low = (url or "").lower()
    if any(t in low for t in [".gov", "startupindia.gov", "seedfund.startupindia"]):
        return "free"
    if any(t in low for t in ["apply", "application", "enroll", "challenge"]):
        return "application_based"
    if any(t in low for t in ["paid", "premium", "demo-booking", "login.seamless"]):
        return "paid_or_mixed"
    return "free_core"


def clean_pdf_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip().rstrip(".,);")
    low = url.lower()
    if any(bad in low for bad in [
        "google.com/search", "webcache.googleusercontent",
        "youtube.com/playlist", "linkedin.com/posts", "linkedin.com/pulse",
        "docs.google.com/spreadsheets", "tildacdn.com", "ctfassets.net",
        "zmdownload.zoho", "mail.google.com", "play.google.com/store",
        "facebook.com", "instagram.com", "twitter.com/i/", "t.me/",
        "wa.me/", "bit.ly/", "metamask.com-update",
    ]):
        return ""
    url = url.strip('"').strip("'")
    return url


# ============================================================
# PDF CATALOG STATISTICS + MATCHING
# ============================================================

def pdf_catalog_stats() -> Dict[str, Any]:
    by_category: Dict[str, int] = {}
    by_access: Dict[str, int] = {}
    by_geography: Dict[str, int] = {}
    india_count = 0
    early_stage_count = 0

    for item in PDF_SOURCE_CATALOG:
        by_category[item["kind"]] = by_category.get(item["kind"], 0) + 1
        by_access[item["access"]] = by_access.get(item["access"], 0) + 1
        for geo in item.get("geography", []):
            by_geography[geo] = by_geography.get(geo, 0) + 1
        if "India" in item.get("geography", []):
            india_count += 1
        if any(s in item.get("stage", []) for s in ["pre-seed", "seed", "early"]):
            early_stage_count += 1

    return {
        "total": len(PDF_SOURCE_CATALOG),
        "india": india_count,
        "early_stage": early_stage_count,
        "by_category": by_category,
        "by_access": by_access,
        "by_geography": by_geography,
    }


def match_pdf_sources(
    startup: StartupProfile,
    stage: Optional[str] = None,
    geography: Optional[str] = None,
    access: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    target_stage = (stage or startup.stage or "early").lower()
    target_geos = [g.lower() for g in (startup.target_geographies or [startup.geography])]
    if geography:
        target_geos.append(geography.lower())

    stage_aliases = {
        "pre-seed": ["pre-seed", "pre seed", "preseed", "any"],
        "preseed":  ["pre-seed", "pre seed", "preseed", "any"],
        "seed":     ["seed", "early", "any"],
        "early":    ["early", "seed", "any"],
        "early stage": ["early", "seed", "any"],
        "series a": ["growth", "early", "any"],
        "growth":   ["growth", "any"],
        "any":      ["pre-seed", "seed", "early", "growth", "any"],
    }
    allowed_stages = stage_aliases.get(target_stage, ["pre-seed", "seed", "early", "any"])

    results: List[Dict[str, Any]] = []
    for item in PDF_SOURCE_CATALOG:
        item_stages = [s.lower() for s in item.get("stage", ["any"])]
        if not any(s in allowed_stages for s in item_stages):
            continue
        if access and item.get("access") != access:
            continue
        item_geos = [g.lower() for g in item.get("geography", ["Global"])]
        geo_hit = any(
            tg in ig or ig in tg or ig == "global" or "global" in ig
            for tg in target_geos for ig in item_geos
        )
        if not geo_hit and "global" not in item_geos and "Global" not in item.get("geography", []):
            continue
        results.append({**item, "geo_match": geo_hit})

    def rank(item: Dict[str, Any]) -> Tuple[int, int, int]:
        india = 1 if "India" in item.get("geography", []) else 0
        early = 1 if any(s in item.get("stage", []) for s in ["pre-seed", "seed", "early"]) else 0
        free = 1 if item.get("access") in ("free", "free_core") else 0
        return (india + early + free, india, early)

    results.sort(key=rank, reverse=True)
    return results[:limit]


def pdf_sources_as_resources(
    startup: StartupProfile,
    mode: str = "fundraising",
    limit: int = 20,
) -> List[Dict[str, Any]]:
    matched = match_pdf_sources(startup, limit=limit)
    output = []
    for item in matched:
        output.append({
            "id": item["id"],
            "name": item["name"],
            "kind": "resource",
            "type": "RESOURCE",
            "url": item["url"],
            "description": item["description"],
            "access": item.get("access", "free_core"),
            "stage": item.get("stage", ["any"]),
            "geography": item.get("geography", ["Global"]),
            "mode": item.get("mode", [mode]),
            "relevance": 0.90,
            "source": "pdf_catalog",
            "opportunity_id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{startup.company_name}:pdf:{item['id']}",
                )
            ),
            "priority": "high",
            "status": "resource",
            "next_action": "verify_current_terms_and_opening",
        })
    return output


# ============================================================
# DOMAIN FILTERS
# ============================================================

NON_ORG_DOMAINS = {
    "linkedin.com", "medium.com", "reddit.com", "wikipedia.org",
    "crunchbase.com", "tracxn.com", "yourstory.com", "inc42.com",
    "techcrunch.com", "forbes.com", "economictimes.indiatimes.com",
    "economictimes.com", "moneycontrol.com", "x.com", "twitter.com",
    "producthunt.com", "news.ycombinator.com", "github.com",
    "openvc.app", "f6s.com", "ycombinator.com", "indiamart.com",
}


GENERIC_NAMES = {
    "venture capital", "venture capital firms", "venture capital investors",
    "venture capital funds", "vc funds", "vc investors", "seed investors",
    "seed funds", "angel investors", "investors in india",
    "startup investors", "startup funding", "investor directory",
    "investor list", "investment firms", "investment funds",
    "funding firms", "early stage investors", "investors",
    "investment companies", "venture firms", "fund managers",
    "startup funds",
}


GENERIC_TOKENS = {
    "top", "best", "list", "guide", "directory", "ranking", "rankings",
    "investors", "funding", "startups", "investment", "companies",
}


CATEGORY_TERMS = {
    "VC": ["venture capital", "venture fund", "venture investor"],
    "ANGEL": ["angel investor", "angel network", "angel fund"],
    "ACCELERATOR": ["accelerator", "accelerator program"],
    "INCUBATOR": ["incubator", "incubation"],
    "FAMILY_OFFICE": ["family office"],
    "FOUNDATION": ["foundation", "impact investor"],
    "LP": ["limited partner", "fund of funds"],
    "GRANT": ["grant", "non-dilutive", "non dilutive"],
}


# ============================================================
# CACHE
# ============================================================

_cache_lock = asyncio.Lock()


def _init_cache() -> None:
    directory = os.path.dirname(CACHE_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with sqlite3.connect(CACHE_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                cache_key TEXT PRIMARY KEY,
                cache_type TEXT NOT NULL,
                expires_at REAL NOT NULL,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_expiry ON cache(expires_at)"
        )
        conn.commit()


_init_cache()


async def cache_get(cache_type: str, key: str) -> Optional[Any]:
    cache_key = f"{cache_type}:{key}"
    async with _cache_lock:
        try:
            with sqlite3.connect(CACHE_PATH) as conn:
                row = conn.execute(
                    "SELECT expires_at, value FROM cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if not row:
                    return None
                expires_at, value = row
                if expires_at <= time.time():
                    conn.execute("DELETE FROM cache WHERE cache_key = ?", (cache_key,))
                    conn.commit()
                    return None
                return json.loads(value)
        except Exception as exc:
            print(f"Cache read failed: {exc}")
            return None


async def cache_set(cache_type: str, key: str, value: Any, ttl: int) -> None:
    cache_key = f"{cache_type}:{key}"
    async with _cache_lock:
        try:
            with sqlite3.connect(CACHE_PATH) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO cache
                    (cache_key, cache_type, expires_at, value)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        cache_key,
                        cache_type,
                        time.time() + ttl,
                        json.dumps(value, ensure_ascii=False),
                    ),
                )
                conn.commit()
        except Exception as exc:
            print(f"Cache write failed: {exc}")


async def cache_cleanup() -> None:
    async with _cache_lock:
        try:
            with sqlite3.connect(CACHE_PATH) as conn:
                conn.execute("DELETE FROM cache WHERE expires_at <= ?", (time.time(),))
                conn.commit()
        except Exception as exc:
            print(f"Cache cleanup failed: {exc}")


# ============================================================
# BUDGET
# ============================================================

class RequestBudget:

    def __init__(self, tier: str):
        self.tier = tier if tier in BUDGETS else "balanced"
        self.remaining = dict(BUDGETS[self.tier])
        self.used = {key: 0 for key in BUDGETS[self.tier]}
        self._lock = asyncio.Lock()

    async def consume(self, provider: str) -> bool:
        async with self._lock:
            if self.remaining.get(provider, 0) <= 0:
                return False
            self.remaining[provider] -= 1
            self.used[provider] += 1
            return True

    def snapshot(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "used": dict(self.used),
            "remaining": dict(self.remaining),
        }


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def normalize_name(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"[^a-z0-9\s&]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        host = (urlparse(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = re.sub(r"/+$", "", parsed.path or "/")
        return urlunparse((parsed.scheme.lower() or "https", host, path, "", "", ""))
    except Exception:
        return ""


def domain_from_url(url: str) -> str:
    return normalize_url(url)


def hash_key(*parts: Any) -> str:
    payload = "||".join(normalize_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# INTENT
# ============================================================

def detect_mode(query: str, requested_mode: str = "auto") -> str:
    if requested_mode != "auto":
        return requested_mode
    q = normalize_text(query)
    patterns = [
        ("customer_acquisition", [
            "acquire customers", "get customers", "find customers",
            "customer acquisition", "customer leads", "sales leads",
            "prospects", "buyers", "distributors", "retailers",
            "b2b customers", "early customers", "design partners",
        ]),
        ("incubation", [
            "incubation", "incubator", "startup program",
            "startup accelerator", "apply to accelerator",
            "apply for incubation",
        ]),
        ("application", [
            "application", "apply", "eligibility", "deadline", "admission",
        ]),
        ("fundraising", [
            "fundraising", "raise money", "raise capital", "funding",
            "investor", "grant", "vc", "angel", "family office",
        ]),
        ("pitching", [
            "pitch deck", "pitch", "investor outreach",
            "cold email", "fundraising deck",
        ]),
        ("validation", [
            "validate", "validation", "idea validation",
            "customer discovery", "market validation",
            "problem validation", "would pay",
        ]),
        ("partnership", [
            "partner", "partnership", "channel partner",
            "strategic partner", "distribution partner",
        ]),
        ("traction", [
            "traction", "customers", "growth", "users",
            "distribution", "launch", "early adopters",
        ]),
    ]
    for mode, terms in patterns:
        if any(term in q for term in terms):
            return mode
    return "investor_discovery"


def detect_geography(query: str) -> str:
    q = normalize_text(query)
    aliases = [
        ("United Arab Emirates", ["united arab emirates", "uae"]),
        ("India", ["india", "indian"]),
        ("Singapore", ["singapore"]),
        ("United Kingdom", ["united kingdom", "uk", "britain"]),
        ("United States", ["united states", "usa", "us startup", "american startup"]),
    ]
    for geography, values in aliases:
        if any(value in q for value in values):
            return geography
    return "India"


def detect_stage(query: str) -> str:
    q = normalize_text(query)
    if "pre-seed" in q or "pre seed" in q:
        return "pre-seed"
    if "series a" in q:
        return "Series A"
    if "seed" in q:
        return "seed"
    return "early stage"


def detect_categories(query: str) -> List[str]:
    q = f" {normalize_text(query)} "
    aliases = {
        "VC": [" vc ", "venture capital", "venture fund"],
        "ANGEL": ["angel", "angel investor"],
        "ACCELERATOR": ["accelerator"],
        "INCUBATOR": ["incubator"],
        "FAMILY_OFFICE": ["family office"],
        "FOUNDATION": ["foundation", "impact investor"],
        "LP": [" lp ", "limited partner", "fund of funds"],
        "GRANT": ["grant", "non-dilutive", "non dilutive"],
        "CUSTOMER": [
            "customer", "buyer", "buyers", "prospect",
            "distributor", "retailer",
        ],
        "PARTNER": ["partner", "partnership", "channel partner"],
    }
    found = [
        category for category, terms in aliases.items()
        if any(term in q for term in terms)
    ]
    return found or ["VC", "ANGEL", "ACCELERATOR", "INCUBATOR", "GRANT"]


# ============================================================
# QUERY BUILDING
# ============================================================

def build_mode_queries(user_query: str, mode: str, budget_tier: str) -> List[Dict[str, str]]:
    geography = detect_geography(user_query)
    stage = detect_stage(user_query)
    categories = detect_categories(user_query)
    queries: List[Dict[str, str]] = []

    if mode == "customer_acquisition":
        queries.extend([
            {"category": "CUSTOMER", "strategy": "buyer",
             "query": f'"{user_query}" buyers customers "{geography}"'},
            {"category": "CUSTOMER", "strategy": "prospects",
             "query": f'"{user_query}" companies procurement "{geography}"'},
            {"category": "CUSTOMER", "strategy": "distribution",
             "query": f'"{user_query}" distributors retailers resellers "{geography}"'},
            {"category": "CUSTOMER", "strategy": "pain_signal",
             "query": f'"{user_query}" complaints alternatives customers'},
            {"category": "PARTNER", "strategy": "channel",
             "query": f'"{user_query}" channel partners strategic partners'},
        ])
    elif mode == "incubation":
        queries.extend([
            {"category": "INCUBATOR", "strategy": "program",
             "query": f'"{geography}" startup incubator "{stage}" application'},
            {"category": "ACCELERATOR", "strategy": "program",
             "query": f'"{geography}" startup accelerator "{stage}" application'},
            {"category": "APPLICATION_PROGRAM", "strategy": "eligibility",
             "query": f'"{geography}" startup incubation accelerator eligibility "{stage}"'},
            {"category": "GRANT", "strategy": "support",
             "query": f'"{geography}" startup grant non-dilutive "{stage}"'},
        ])
    elif mode == "application":
        queries.extend([
            {"category": "APPLICATION_PROGRAM", "strategy": "apply",
             "query": f'"{geography}" startup apply accelerator incubator "{stage}"'},
            {"category": "ACCELERATOR", "strategy": "application",
             "query": f'"{geography}" accelerator application startup "{stage}"'},
            {"category": "INCUBATOR", "strategy": "application",
             "query": f'"{geography}" incubator application startup "{stage}"'},
            {"category": "GRANT", "strategy": "application",
             "query": f'"{geography}" startup grant application "{stage}"'},
        ])
    elif mode == "fundraising":
        queries.extend([
            {"category": "GRANT", "strategy": "grant",
             "query": f'"{geography}" startup grant "{stage}" non-dilutive'},
            {"category": "ACCELERATOR", "strategy": "accelerator",
             "query": f'"{geography}" startup accelerator "{stage}" funding'},
            {"category": "INCUBATOR", "strategy": "incubator",
             "query": f'"{geography}" startup incubator funding "{stage}"'},
            {"category": "VC", "strategy": "investor",
             "query": f'"{geography}" "{stage}" startup venture capital investor'},
            {"category": "ANGEL", "strategy": "angel",
             "query": f'"{geography}" "{stage}" startup angel investor'},
            {"category": "FAMILY_OFFICE", "strategy": "family_office",
             "query": f'"{geography}" family office startup investment "{stage}"'},
        ])
    elif mode == "pitching":
        queries.extend([
            {"category": "VC", "strategy": "pitch",
             "query": f'"{user_query}" startup pitch investor'},
            {"category": "VC", "strategy": "thesis",
             "query": f'"{user_query}" investment thesis "{stage}"'},
            {"category": "APPLICATION_PROGRAM", "strategy": "demo_day",
             "query": f'"{user_query}" accelerator demo day pitch'},
        ])
    elif mode == "validation":
        queries.extend([
            {"category": "CUSTOMER", "strategy": "pain",
             "query": f'"{user_query}" customer pain problem complaints'},
            {"category": "CUSTOMER", "strategy": "alternatives",
             "query": f'"{user_query}" alternatives competitors customers'},
            {"category": "CUSTOMER", "strategy": "willingness_to_pay",
             "query": f'"{user_query}" "would pay" OR "pay for"'},
            {"category": "COMMUNITY", "strategy": "community",
             "query": f'"{user_query}" Reddit Hacker News discussion'},
        ])
    elif mode == "traction":
        queries.extend([
            {"category": "COMMUNITY", "strategy": "distribution",
             "query": f'"{user_query}" early adopters community launch'},
            {"category": "CUSTOMER", "strategy": "demand",
             "query": f'"{user_query}" customers buying demand market'},
            {"category": "CUSTOMER", "strategy": "feedback",
             "query": f'"{user_query}" customer feedback complaints'},
        ])
    elif mode == "partnership":
        queries.extend([
            {"category": "PARTNER", "strategy": "channel",
             "query": f'"{user_query}" channel partners distribution'},
            {"category": "PARTNER", "strategy": "strategic",
             "query": f'"{user_query}" strategic partnership ecosystem'},
            {"category": "PARTNER", "strategy": "integration",
             "query": f'"{user_query}" integration partner platform'},
        ])
    else:
        for category in categories:
            if category == "VC":
                strategies = [
                    ("direct", f'"{geography}" "venture capital" "{stage}" startups'),
                    ("portfolio", f'"{geography}" VC portfolio startups "{stage}"'),
                    ("thesis", f'"{geography}" investment thesis "{stage}"'),
                ]
            elif category == "ANGEL":
                strategies = [("direct", f'"{geography}" angel investor "{stage}" startups')]
            elif category == "ACCELERATOR":
                strategies = [("program", f'"{geography}" startup accelerator "{stage}"')]
            elif category == "INCUBATOR":
                strategies = [("program", f'"{geography}" startup incubator "{stage}"')]
            elif category == "GRANT":
                strategies = [("grant", f'"{geography}" startup grant "{stage}"')]
            elif category == "CUSTOMER":
                strategies = [("buyer", f'"{user_query}" buyers customers "{geography}"')]
            else:
                strategies = [("direct", f'"{geography}" {category.lower()} startup')]

            for strategy, built_query in strategies:
                queries.append({"category": category, "strategy": strategy, "query": built_query})

    max_queries = {"cheap": 7, "balanced": 11, "deep": 16}.get(budget_tier, 11)

    seen = set()
    output = []
    for item in queries:
        key = normalize_text(item["query"])
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
        if len(output) >= max_queries:
            break
    return output


# ============================================================
# PROVIDER SEARCH
# ============================================================

async def exa_search(
    item: Dict[str, str],
    budget: RequestBudget,
    adaptive: bool = False,
) -> List[Dict[str, Any]]:

    provider_budget = "adaptive_exa" if adaptive else "exa"
    cache_key = hash_key(item["query"], EXA_MAX_RESULTS, EXA_TEXT_LIMIT)
    cached = await cache_get("search", cache_key)
    if cached is not None:
        return cached
    if not await budget.consume(provider_budget):
        return []

    try:
        response = await asyncio.to_thread(
            exa_client.search,
            item["query"],
            type="auto",
            num_results=EXA_MAX_RESULTS,
            contents={"text": {"max_characters": EXA_TEXT_LIMIT}},
        )
        output = []
        for result in (getattr(response, "results", []) or []):
            url = canonical_url(getattr(result, "url", "") or "")
            if not url:
                continue
            output.append({
                "title": (getattr(result, "title", "") or "")[:300],
                "content": (getattr(result, "text", "") or "")[:EXA_TEXT_LIMIT],
                "url": url,
                "author": (getattr(result, "author", "") or "")[:200],
                "published_date": (getattr(result, "published_date", "") or ""),
                "provider": "exa",
                "category": item["category"],
                "strategy": item["strategy"],
                "search_query": item["query"],
                "score": float(getattr(result, "score", 0) or 0),
            })
        await cache_set("search", cache_key, output, SEARCH_CACHE_TTL)
        return output
    except Exception as exc:
        print(f"Exa failed: {exc}")
        return []


async def tavily_search(
    query: str,
    category: str,
    purpose: str,
    budget: RequestBudget,
    depth: str = "light",
) -> List[Dict[str, Any]]:

    cache_key = hash_key(query, category, purpose, MAX_TAVILY_RESULTS, depth)
    cached = await cache_get("evidence", cache_key)
    if cached is not None:
        return cached
    if not await budget.consume("tavily"):
        return []

    try:
        search_depth = "advanced" if depth == "deep" else "basic"
        response = await asyncio.to_thread(
            tavily_client.search,
            query=query,
            search_depth=search_depth,
            max_results=MAX_TAVILY_RESULTS,
            include_answer=False,
            include_raw_content=False,
        )
        results = []
        for item in (response.get("results", []) or []):
            url = canonical_url(item.get("url", "") or "")
            if not url:
                continue
            results.append({
                "title": (item.get("title", "") or "")[:300],
                "content": (item.get("content", "") or "")[:TAVILY_CONTENT_LIMIT],
                "url": url,
                "score": float(item.get("score", 0) or 0),
                "provider": "tavily",
                "category": category,
                "purpose": purpose,
                "search_query": query,
            })
        await cache_set("evidence", cache_key, results, EVIDENCE_CACHE_TTL)
        return results
    except Exception as exc:
        print(f"Tavily failed: {exc}")
        return []


# ============================================================
# ENTITY EXTRACTION
# ============================================================

def clean_organization_name(name: str) -> str:
    name = re.sub(r"^[\s\-–—|:;,]+", "", (name or "").strip())
    name = re.sub(r"[\s\-–—|:;,]+$", "", name)
    name = re.split(
        r"\s+(?:is|are|was|were|has|have|provides|offers|invests|invested|"
        r"investing|backs|backed|focuses|specializes)\b",
        name, maxsplit=1, flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", name).strip(" -–—|:;,.")


def looks_generic(name: str) -> bool:
    normalized = normalize_name(name)
    if (not normalized or normalized in GENERIC_NAMES or normalized in GENERIC_TOKENS):
        return True
    return any(
        re.search(pattern, normalized)
        for pattern in [
            r"^top\s+", r"^best\s+", r"^list\s+of\s+", r"^ranking",
            r"^guide\b", r"^directory\b", r"^how\s+to\b", r"^who\s+",
            r"^investors?\s+in\s+", r"^venture\s+capital\s+firms?",
            r"^angel\s+investors?", r"\bin\s+india$", r"\bfor\s+startups$",
        ]
    )


def is_valid_organization(name: str) -> bool:
    name = clean_organization_name(name)
    if not name:
        return False
    if looks_generic(name):
        return False
    if len(name) < 2:
        return False
    if len(name) > 100:
        return False
    if len(name.split()) > 8:
        return False
    return not name.endswith((".", "?", "!"))


def is_listicle(title: str) -> bool:
    title = normalize_text(title)
    if not title:
        return True
    return any(
        re.search(pattern, title)
        for pattern in [
            r"^top\s+", r"^best\s+", r"list\s+of", r"ranking",
            r"directory", r"\bguide\b", "investors in india",
            "venture capital firms", "startup investors", r"\b20\d{2}\b",
        ]
    )


def domain_brand(url: str) -> str:
    domain = domain_from_url(url)
    if not domain:
        return ""
    first = domain.split(".")[0]
    if first in {"blog", "news", "about", "app", "mail", "www"}:
        return ""
    return first.replace("-", " ").replace("_", " ").title()


def title_brand(title: str) -> str:
    if not title:
        return ""
    candidate = re.split(r"\s+[|:\-–—]\s+", title, maxsplit=1)[0].strip()
    candidate = clean_organization_name(candidate)
    return candidate if is_valid_organization(candidate) else ""


def extract_organization(result: Dict[str, Any]) -> Optional[str]:
    title = result.get("title", "")
    content = result.get("content", "")
    url = result.get("url", "")

    if title and not is_listicle(title):
        candidate = title_brand(title)
        if candidate:
            return candidate

    combined = f"{title}\n{content[:EXA_TEXT_LIMIT]}"

    patterns = [
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)\s+(?:is|are)\s+(?:a|an|the)\s+"
        r"(?:venture capital|venture|investment|angel|accelerator|incubator|"
        r"family office|foundation)\b",
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)\s+(?:invests|invested|investing)\s+(?:in|into)\b",
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)\s+(?:backs|backed|backing)\b",
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)\s+(?:portfolio|portfolio companies)\b",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, combined, flags=re.IGNORECASE)
        for match in matches:
            candidate = clean_organization_name(match if isinstance(match, str) else match[0])
            if is_valid_organization(candidate):
                return candidate

    text = normalize_text(combined)
    if any(term in text for term in [
        "invests", "portfolio", "venture capital", "angel investor",
        "accelerator", "incubator", "family office", "foundation",
    ]):
        candidate = domain_brand(url)
        if is_valid_organization(candidate):
            return candidate
    return None


# ============================================================
# RESULT SCORING
# ============================================================

def result_relevance_score(result: Dict[str, Any]) -> float:
    title = normalize_text(result.get("title", ""))
    content = normalize_text(result.get("content", ""))
    domain = domain_from_url(result.get("url", ""))

    score = min(0.35, max(0.0, float(result.get("score", 0) or 0)) * 0.35)
    if domain and domain not in NON_ORG_DOMAINS:
        score += 0.20
    if any(term in title for term in [
        "portfolio", "investment", "investor", "ventures", "capital",
        "accelerator", "incubator", "customers", "buyers",
    ]):
        score += 0.15
    if any(term in content for term in [
        "we invest", "our portfolio", "our investments",
        "investment thesis", "we back", "our customers", "our clients",
    ]):
        score += 0.20
    if is_listicle(title):
        score -= 0.20
    return max(0.0, min(1.0, score))


def merge_candidates(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}
    seen_urls = set()

    for result in results:
        url = canonical_url(result.get("url", ""))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        organization = extract_organization(result)
        if not organization:
            continue

        normalized = normalize_name(organization)
        if not normalized:
            continue

        candidate = candidates.setdefault(normalized, {
            "name": organization,
            "normalized_name": normalized,
            "results": [],
            "categories": set(),
            "strategies": set(),
            "domains": set(),
            "discovery_count": 0,
            "best_discovery_score": 0.0,
        })

        candidate["results"].append(result)
        candidate["categories"].add(result.get("category", "UNKNOWN"))
        candidate["strategies"].add(result.get("strategy", "unknown"))

        domain = domain_from_url(url)
        if domain:
            candidate["domains"].add(domain)

        candidate["discovery_count"] += 1
        candidate["best_discovery_score"] = max(
            candidate["best_discovery_score"],
            result_relevance_score(result),
        )

    output = []
    for candidate in candidates.values():
        candidate["categories"] = sorted(candidate["categories"])
        candidate["strategies"] = sorted(candidate["strategies"])
        candidate["domains"] = sorted(candidate["domains"])
        candidate["discovery_score"] = round(
            min(
                1.0,
                candidate["best_discovery_score"] * 0.60
                + min(1.0, candidate["discovery_count"] / 4) * 0.25
                + min(1.0, len(candidate["strategies"]) / 3) * 0.10
                + min(1.0, len(candidate["domains"]) / 2) * 0.05,
            ),
            3,
        )
        output.append(candidate)

    output.sort(key=lambda x: (x["discovery_score"], x["discovery_count"]), reverse=True)
    return output[:MAX_CANDIDATES]


# ============================================================
# EVIDENCE
# ============================================================

def build_evidence_queries(
    candidate: Dict[str, Any],
    user_query: str,
    depth: str,
    mode: str,
) -> List[Tuple[str, str]]:

    name = candidate["name"]
    geography = detect_geography(user_query)
    stage = detect_stage(user_query)
    categories = candidate.get("categories") or ["VC"]
    category = categories[0]

    if mode == "customer_acquisition":
        queries = [
            (f'"{name}" customers buyers products services', "customer_fit"),
            (f'"{name}" procurement purchasing partnership', "outreach_path"),
            (f'"{name}" suppliers distributors vendors', "commercial_signal"),
        ]
    elif mode in {"incubation", "application"}:
        queries = [
            (f'"{name}" application eligibility startup program', "application"),
            (f'"{name}" deadline cohort funding incubation', "program_details"),
            (f'"{name}" fees startup application', "cost"),
        ]
    elif mode == "validation":
        queries = [
            (f'"{name}" customers reviews complaints', "customer_signal"),
            (f'"{name}" alternatives competitors', "alternative"),
        ]
    elif mode == "traction":
        queries = [(f'"{name}" customers users growth', "customer_signal")]
    elif mode == "pitching":
        queries = [
            (f'"{name}" investment thesis portfolio startups', "pitch_fit"),
            (f'"{name}" application pitch startup', "pitch_process"),
        ]
    elif category == "GRANT":
        queries = [
            (f'"{name}" grant eligibility application', "grant"),
            (f'"{name}" grant deadline funding', "grant_details"),
        ]
    elif category == "LP":
        queries = [(f'"{name}" limited partner venture capital fund', "lp_relationship")]
    else:
        queries = [
            (f'"{name}" "{geography}" "{stage}" startups investment', "investment"),
            (f'"{name}" portfolio startups investment thesis', "portfolio"),
        ]

    return queries[:1] if depth == "light" else queries[:2]


def evidence_signals(text: str, category: str, user_query: str, mode: str) -> Dict[str, float]:
    text = normalize_text(text)
    geography = normalize_text(detect_geography(user_query))
    stage = normalize_text(detect_stage(user_query))

    signals = {
        "investment": 0.0, "geography": 0.0, "stage": 0.0, "portfolio": 0.0,
        "transaction": 0.0, "official": 0.0, "category": 0.0, "traction": 0.0,
        "customer": 0.0, "buyer": 0.0, "program": 0.0, "application": 0.0,
        "free_resource": 0.0, "contradiction": 0.0,
    }

    if any(term in text for term in [
        "invests", "invested", "investing", "investment", "backs", "backed",
    ]):
        signals["investment"] = 1.0
    if geography in text or geography.replace(" ", "") in text:
        signals["geography"] = 1.0
    stage_terms = {
        "pre-seed": ["pre-seed", "pre seed"],
        "seed": ["seed stage", "seed-stage", "seed round"],
        "early stage": ["early stage", "early-stage"],
        "series a": ["series a"],
    }.get(stage, [stage])
    if any(term in text for term in stage_terms):
        signals["stage"] = 1.0
    if any(term in text for term in [
        "portfolio", "portfolio company", "portfolio companies",
    ]):
        signals["portfolio"] = 1.0
    if any(term in text for term in [
        "funding round", "seed round", "series a",
        "investment round", "raised $", "raised usd",
    ]):
        signals["transaction"] = 1.0
    if any(term in text for term in [
        "our portfolio", "our investments", "we invest",
        "we back", "investment thesis", "about us", "official",
    ]):
        signals["official"] = 1.0
    if any(term in text for term in CATEGORY_TERMS.get(category, [])):
        signals["category"] = 1.0
    if any(term in text for term in [
        "users", "customers", "adoption", "growth", "traction", "revenue",
    ]):
        signals["traction"] = 1.0
    if any(term in text for term in [
        "customer", "customers", "client", "clients",
        "pain point", "problem", "complaint", "review",
    ]):
        signals["customer"] = 1.0
    if any(term in text for term in [
        "buyer", "buyers", "procurement", "purchasing", "supplier", "vendor",
    ]):
        signals["buyer"] = 1.0
    if any(term in text for term in [
        "accelerator", "incubator", "program", "cohort",
    ]):
        signals["program"] = 1.0
    if any(term in text for term in [
        "apply", "application", "eligibility", "deadline",
    ]):
        signals["application"] = 1.0
    if any(term in text for term in [
        "free", "no cost", "no fee", "free to apply",
    ]):
        signals["free_resource"] = 1.0
    if any(term in text for term in [
        "does not invest", "do not invest", "no longer invests",
        "not an investor", "not eligible",
    ]):
        signals["contradiction"] = 1.0
    return signals


def source_quality(result: Dict[str, Any]) -> float:
    url = result.get("url", "")
    title = normalize_text(result.get("title", ""))
    content = normalize_text(result.get("content", ""))
    domain = domain_from_url(url)

    score = 0.0
    if domain in {"gov.in", "startupindia.gov.in", "seedfund.startupindia.gov.in"}:
        score += 0.55
    elif domain and domain not in NON_ORG_DOMAINS:
        score += 0.30
    if any(term in content for term in [
        "we invest", "our portfolio", "our investments",
        "investment thesis", "we back", "official",
        "apply", "eligibility",
    ]):
        score += 0.30
    if any(term in title for term in [
        "portfolio", "investment", "thesis", "funding",
        "grant", "application", "program",
    ]):
        score += 0.15
    if not is_listicle(title):
        score += 0.10
    if result.get("provider") == "tavily":
        score += 0.05
    return min(score, 1.0)


# ============================================================
# FRESHNESS
# ============================================================

def parse_date_timestamp(value: str) -> Optional[float]:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def freshness_score(published_date: str) -> float:
    timestamp = parse_date_timestamp(published_date)
    if not timestamp:
        return 0.45
    age_days = max(0, (time.time() - timestamp) / 86400)
    if age_days <= 30:
        return 1.0
    if age_days <= 90:
        return 0.90
    if age_days <= 180:
        return 0.75
    if age_days <= 365:
        return 0.60
    if age_days <= 730:
        return 0.40
    return 0.20


# ============================================================
# VERIFICATION
# ============================================================

async def verify_candidate(
    candidate: Dict[str, Any],
    user_query: str,
    budget: RequestBudget,
    depth: str,
    mode: str,
) -> Dict[str, Any]:

    category = (candidate.get("categories") or ["VC"])[0]

    profile_key = hash_key(
        candidate["normalized_name"], category,
        detect_geography(user_query), detect_stage(user_query),
        depth, mode,
    )
    cached = await cache_get("profile", profile_key)
    if cached is not None:
        return cached

    queries = build_evidence_queries(candidate, user_query, depth, mode)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

    async def run(query: str, purpose: str):
        async with semaphore:
            return await tavily_search(query, category, purpose, budget, depth)

    responses = await asyncio.gather(
        *[run(q, p) for q, p in queries],
        return_exceptions=True,
    )

    evidence: List[Dict[str, Any]] = []
    for response in responses:
        if isinstance(response, list):
            evidence.extend(response)

    unique_sources: Dict[str, Dict[str, Any]] = {}
    for item in evidence:
        url = canonical_url(item.get("url", ""))
        if not url:
            continue
        current = unique_sources.get(url)
        if (
            current is None
            or float(item.get("score", 0) or 0) > float(current.get("score", 0) or 0)
        ):
            unique_sources[url] = item
    evidence = list(unique_sources.values())

    aggregated = {
        key: 0.0
        for key in [
            "investment", "geography", "stage", "portfolio", "transaction",
            "official", "category", "traction", "customer", "buyer",
            "program", "application", "free_resource", "contradiction",
        ]
    }
    domains: Set[str] = set()
    evidence_items: List[Dict[str, Any]] = []
    quality_scores: List[float] = []
    freshness_scores: List[float] = []

    for item in evidence:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        signals = evidence_signals(text, category, user_query, mode)
        quality = source_quality(item)
        freshness = freshness_score(item.get("published_date", ""))
        quality_scores.append(quality)
        freshness_scores.append(freshness)
        domain = domain_from_url(item.get("url", ""))
        if domain:
            domains.add(domain)
        for key in aggregated:
            aggregated[key] = max(aggregated[key], signals[key])
        evidence_items.append({
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "content": (item.get("content", "") or "")[:EVIDENCE_LIMIT],
            "quality": round(quality, 3),
            "freshness": round(freshness, 3),
            "published_date": item.get("published_date", ""),
            "search_query": item.get("search_query", ""),
            "signals": signals,
        })

    diversity = min(1.0, len(domains) / 3)
    average_quality = (sum(quality_scores) / len(quality_scores)) if quality_scores else 0.0
    average_freshness = (sum(freshness_scores) / len(freshness_scores)) if freshness_scores else 0.0

    if mode == "customer_acquisition":
        evidence_score = (
            aggregated["customer"] * 0.20
            + aggregated["buyer"] * 0.20
            + aggregated["geography"] * 0.10
            + aggregated["official"] * 0.12
            + aggregated["traction"] * 0.08
            + diversity * 0.10
            + average_quality * 0.05
            + average_freshness * 0.10
            - aggregated["contradiction"] * 0.25
        )
    elif mode in {"incubation", "application"}:
        evidence_score = (
            aggregated["program"] * 0.22
            + aggregated["application"] * 0.20
            + aggregated["geography"] * 0.10
            + aggregated["stage"] * 0.10
            + aggregated["official"] * 0.15
            + average_quality * 0.08
            + average_freshness * 0.10
            - aggregated["contradiction"] * 0.30
        )
    elif mode == "fundraising":
        evidence_score = (
            aggregated["investment"] * 0.20
            + aggregated["transaction"] * 0.10
            + aggregated["stage"] * 0.10
            + aggregated["geography"] * 0.10
            + aggregated["portfolio"] * 0.10
            + aggregated["official"] * 0.12
            + aggregated["category"] * 0.06
            + average_quality * 0.07
            + average_freshness * 0.10
            - aggregated["contradiction"] * 0.30
        )
    elif mode in {"traction", "validation"}:
        evidence_score = (
            aggregated["customer"] * 0.18
            + aggregated["buyer"] * 0.15
            + aggregated["traction"] * 0.20
            + aggregated["geography"] * 0.08
            + aggregated["official"] * 0.08
            + diversity * 0.10
            + average_quality * 0.08
            + average_freshness * 0.10
            - aggregated["contradiction"] * 0.25
        )
    else:
        evidence_score = (
            aggregated["investment"] * 0.20
            + aggregated["program"] * 0.12
            + aggregated["geography"] * 0.10
            + aggregated["stage"] * 0.10
            + aggregated["portfolio"] * 0.10
            + aggregated["official"] * 0.12
            + aggregated["category"] * 0.08
            + average_quality * 0.08
            + average_freshness * 0.10
            - aggregated["contradiction"] * 0.30
        )

    evidence_score = round(max(0.0, min(1.0, evidence_score)), 3)

    if evidence_score >= 0.70:
        status = "STRONGLY_VERIFIED"
    elif evidence_score >= 0.50:
        status = "VERIFIED"
    elif evidence_score >= 0.35:
        status = "SUPPORTED"
    else:
        status = "WEAK"

    relationship = {
        "LP": "LP_TO_FUND",
        "ACCELERATOR": "ACCELERATOR_TO_STARTUP",
        "INCUBATOR": "INCUBATOR_TO_STARTUP",
        "GRANT": "GRANT_TO_STARTUP",
        "CROWDFUNDING": "CROWDFUNDING_TO_STARTUP",
        "CUSTOMER": "STARTUP_TO_CUSTOMER",
        "PARTNER": "STARTUP_TO_PARTNER",
        "APPLICATION_PROGRAM": "STARTUP_TO_PROGRAM",
    }.get(category, "INVESTOR_TO_STARTUP")

    verified = {
        **candidate,
        "evidence": sorted(
            evidence_items,
            key=lambda x: (x.get("quality", 0) * 0.5 + x.get("freshness", 0) * 0.5),
            reverse=True,
        )[:5],
        "evidence_signals": aggregated,
        "evidence_score": evidence_score,
        "source_diversity": round(diversity, 3),
        "average_source_quality": round(average_quality, 3),
        "average_freshness": round(average_freshness, 3),
        "source_count": len(evidence),
        "domain_count": len(domains),
        "relationship": relationship,
        "verification_status": status,
        "verification_score": evidence_score,
        "verification_depth": depth,
        "mode": mode,
    }

    await cache_set("profile", profile_key, verified, PROFILE_CACHE_TTL)
    return verified


# ============================================================
# FREE SOURCE MATCHING
# ============================================================

def match_free_sources(query: str, mode: str) -> List[Dict[str, Any]]:
    q = normalize_text(query)
    matches = []
    for source in FREE_SOURCE_CATALOG:
        if mode not in source["mode"]:
            continue
        relevance = 0.50
        if any(token in q for token in [
            "fund", "invest", "raise", "grant", "pitch",
            "accelerator", "incubator",
        ]):
            if "fundraising" in source["mode"]:
                relevance += 0.25
        if any(token in q for token in [
            "traction", "customer", "user", "growth", "launch",
        ]):
            if "traction" in source["mode"]:
                relevance += 0.20
        if any(token in q for token in [
            "validate", "idea", "problem", "feedback",
        ]):
            if "validation" in source["mode"]:
                relevance += 0.20
        item = dict(source)
        item["relevance"] = round(min(relevance, 0.99), 2)
        matches.append(item)
    return sorted(matches, key=lambda x: x["relevance"], reverse=True)


def build_free_source_queries(query: str, mode: str) -> List[Dict[str, str]]:
    output = []
    for source in match_free_sources(query, mode):
        for template in source["query_templates"][:2]:
            output.append({
                "category": "RESOURCE",
                "strategy": source["id"],
                "query": template,
                "source_id": source["id"],
            })
    return output[:8]


# ============================================================
# STARTUP PROFILE QUERY GENERATION
# ============================================================

def startup_search_query(startup: StartupProfile) -> str:
    customer_text = ", ".join(startup.customer_types[:5])
    buyer_text = ", ".join(startup.buyer_roles[:5])
    pain_text = ", ".join(startup.pain_points[:5])
    return (
        f"{startup.company_name} "
        f"{startup.product} "
        f"{startup.industry} "
        f"{startup.stage} "
        f"customers {customer_text} "
        f"buyers {buyer_text} "
        f"problems {pain_text} "
        f"{' '.join(startup.target_geographies[:3])}"
    )


# ============================================================
# FIT SCORING
# ============================================================

def token_set(value: str) -> Set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", normalize_text(value))
        if len(token) >= 3
    }


def text_overlap(a: str, b: str) -> float:
    a_tokens = token_set(a)
    b_tokens = token_set(b)
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def opportunity_fit_score(startup: StartupProfile, entity: Dict[str, Any], mode: str) -> float:
    evidence_text = " ".join([item.get("title", "") for item in entity.get("evidence", [])])
    evidence_text += " "
    evidence_text += " ".join([item.get("content", "") for item in entity.get("evidence", [])])

    startup_text = " ".join([
        startup.product, startup.description, startup.industry,
        " ".join(startup.customer_types),
        " ".join(startup.buyer_roles),
        " ".join(startup.pain_points),
    ])

    semantic_fit = text_overlap(startup_text, evidence_text)
    geography_fit = 0.0
    entity_country = normalize_text(entity.get("country", ""))
    for geography in (startup.target_geographies or [startup.geography]):
        if normalize_text(geography) == entity_country:
            geography_fit = 1.0
            break

    verification = float(entity.get("verification_score", 0) or 0)
    freshness = float(entity.get("average_freshness", 0) or 0)

    score = (
        semantic_fit * 0.30
        + geography_fit * 0.15
        + verification * 0.35
        + freshness * 0.20
    )
    return round(min(0.99, max(0.0, score)), 3)


# ============================================================
# ENTITY OBJECT
# ============================================================

def calculate_final_score(candidate: Dict[str, Any]) -> float:
    discovery = float(candidate.get("discovery_score", 0) or 0)
    evidence = float(candidate.get("evidence_score", 0) or 0)
    diversity = float(candidate.get("source_diversity", 0) or 0)
    quality = float(candidate.get("average_source_quality", 0) or 0)
    freshness = float(candidate.get("average_freshness", 0) or 0)
    count = min(1.0, float(candidate.get("discovery_count", 0) or 0) / 4)

    score = (
        discovery * 0.15
        + evidence * 0.50
        + diversity * 0.08
        + quality * 0.07
        + freshness * 0.10
        + count * 0.10
    )
    if candidate.get("verification_status") == "STRONGLY_VERIFIED":
        score += 0.05
    if candidate.get("verification_status") == "WEAK":
        score -= 0.15
    return round(max(0.0, min(score, 0.99)), 3)


def entity_relationship(category: str) -> str:
    return {
        "LP": "LP_TO_FUND",
        "ACCELERATOR": "ACCELERATOR_TO_STARTUP",
        "INCUBATOR": "INCUBATOR_TO_STARTUP",
        "GRANT": "GRANT_TO_STARTUP",
        "CROWDFUNDING": "CROWDFUNDING_TO_STARTUP",
        "CUSTOMER": "STARTUP_TO_CUSTOMER",
        "PARTNER": "STARTUP_TO_PARTNER",
        "APPLICATION_PROGRAM": "STARTUP_TO_PROGRAM",
    }.get(category, "INVESTOR_TO_STARTUP")


def build_entity(
    candidate: Dict[str, Any],
    user_query: str,
    mode: str,
    startup: Optional[StartupProfile] = None,
) -> Optional[Dict[str, Any]]:

    name = candidate.get("name", "")
    if not is_valid_organization(name):
        return None

    final_score = calculate_final_score(candidate)
    if final_score < 0.25:
        return None

    category = (candidate.get("categories") or ["INVESTOR"])[0]
    signals = candidate.get("evidence_signals", {})
    stage = detect_stage(user_query) if signals.get("stage") else "Unknown"
    confidence = min(
        0.99,
        final_score + (0.05 if candidate.get("verification_status") == "STRONGLY_VERIFIED" else 0),
    )

    entity = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, normalize_name(name))),
        "name": name,
        "normalized_name": normalize_name(name),
        "type": category,
        "country": detect_geography(user_query),
        "stage": stage,
        "mode": mode,
        "relationship": entity_relationship(category),
        "confidence": round(confidence, 3),
        "traction": {
            "discovery_count": candidate.get("discovery_count", 0),
            "discovery_score": candidate.get("discovery_score", 0),
            "source_count": candidate.get("source_count", 0),
            "source_diversity": candidate.get("source_diversity", 0),
            "domain_count": candidate.get("domain_count", 0),
        },
        "evidence": candidate.get("evidence", [])[:3],
        "evidence_signals": signals,
        "verification_status": candidate.get("verification_status", "UNKNOWN"),
        "verification_score": candidate.get("verification_score", 0),
        "average_freshness": candidate.get("average_freshness", 0),
        "final_score": final_score,
        "providers": ["exa", "tavily"],
        "source": "Exa discovery + selective Tavily verification",
        "search_query": user_query,
    }

    if startup:
        entity["fit_score"] = opportunity_fit_score(startup, entity, mode)

    return entity


# ============================================================
# OPPORTUNITY TRANSFORMATION
# ============================================================

def opportunity_kind(entity: Dict[str, Any]) -> str:
    category = entity.get("type", "")
    if category == "CUSTOMER":
        return "customer"
    if category == "PARTNER":
        return "partner"
    if category in {"ACCELERATOR", "INCUBATOR", "APPLICATION_PROGRAM"}:
        return "program"
    if category == "GRANT":
        return "grant"
    if category in {"VC", "ANGEL", "FAMILY_OFFICE", "LP"}:
        return "investor"
    return "resource"


def next_action_for_entity(entity: Dict[str, Any]) -> str:
    category = entity.get("type", "")
    if category == "CUSTOMER":
        return "research_buyer_then_send_personalized_outreach"
    if category == "PARTNER":
        return "identify_partnership_owner_then_request_meeting"
    if category in {"ACCELERATOR", "INCUBATOR", "APPLICATION_PROGRAM"}:
        return "verify_current_eligibility_then_prepare_application"
    if category == "GRANT":
        return "verify_eligibility_deadline_then_apply"
    if category in {"VC", "ANGEL", "FAMILY_OFFICE", "LP"}:
        return "verify_investment_fit_then_send_targeted_pitch"
    return "review_source_and_decide_next_step"


def build_opportunity(entity: Dict[str, Any], startup: StartupProfile) -> Dict[str, Any]:
    kind = opportunity_kind(entity)
    fit_score = entity.get("fit_score", entity.get("final_score", 0))
    priority = "high" if fit_score >= 0.70 else "medium" if fit_score >= 0.50 else "low"

    return {
        "opportunity_id": str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{startup.company_name}:{entity['id']}:{kind}",
            )
        ),
        "organization_id": entity["id"],
        "name": entity["name"],
        "type": entity["type"],
        "kind": kind,
        "relationship": entity.get("relationship"),
        "fit_score": fit_score,
        "priority": priority,
        "confidence": entity.get("confidence", 0),
        "verification_status": entity.get("verification_status", "UNKNOWN"),
        "evidence": entity.get("evidence", []),
        "evidence_signals": entity.get("evidence_signals", {}),
        "average_freshness": entity.get("average_freshness", 0),
        "next_action": next_action_for_entity(entity),
        "status": "discovered",
        "startup": startup.company_name,
        "created_at": now_iso(),
    }


# ============================================================
# RELATIONSHIP GRAPH
# ============================================================

def build_relationships(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    relationships = []
    for entity in entities:
        relationship = entity.get("relationship")
        if not relationship:
            continue
        target_type = "STARTUP"
        if relationship == "LP_TO_FUND":
            target_type = "VENTURE_FUND"
            target_name = "Venture Capital Fund"
        elif relationship == "STARTUP_TO_CUSTOMER":
            target_type = "CUSTOMER"
            target_name = "Target Customer"
        elif relationship == "STARTUP_TO_PARTNER":
            target_type = "PARTNER"
            target_name = "Strategic Partner"
        elif relationship == "STARTUP_TO_PROGRAM":
            target_type = "PROGRAM"
            target_name = "Startup Program"
        else:
            target_name = f"{entity.get('stage', 'Early Stage')} Startup"

        target_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                normalize_name(f"{target_type}:{target_name}"),
            )
        )

        relationships.append({
            "id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{entity['id']}:{relationship}:{target_id}",
                )
            ),
            "source": entity["id"],
            "target": target_id,
            "source_name": entity["name"],
            "target_name": target_name,
            "source_type": entity.get("type", "UNKNOWN"),
            "target_type": target_type,
            "relationship": relationship,
            "geography": entity.get("country"),
            "stage": entity.get("stage"),
            "confidence": entity.get("confidence", 0),
            "verification_status": entity.get("verification_status", "UNKNOWN"),
            "evidence": entity.get("evidence", [])[:2],
        })
    return relationships


# ============================================================
# ACTION PLAN
# ============================================================

def build_action_plan(
    startup: StartupProfile,
    opportunities: List[Dict[str, Any]],
    resources: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    customer_count = len([o for o in opportunities if o["kind"] == "customer"])
    investor_count = len([o for o in opportunities if o["kind"] == "investor"])
    program_count = len([o for o in opportunities if o["kind"] == "program"])
    grant_count = len([o for o in opportunities if o["kind"] == "grant"])

    return [
        {
            "step": 1,
            "action": "Validate the ICP",
            "detail": (
                f"Target {', '.join(startup.customer_types[:4])} "
                f"and reach buyer roles such as "
                f"{', '.join(startup.buyer_roles[:4])}."
            ),
            "metric": "qualified interviews / demos",
        },
        {
            "step": 2,
            "action": "Run customer discovery",
            "detail": (
                f"Use the {customer_count} discovered customer opportunities "
                "as a starting list. Prioritize companies showing an "
                "observable pain signal rather than simply matching keywords."
            ),
            "metric": "replies, interviews, demos, pilots",
        },
        {
            "step": 3,
            "action": "Create evidence",
            "detail": (
                "Convert conversations and pilots into measurable proof: "
                "usage, revenue, savings, time reduction, conversion or "
                "other customer outcomes."
            ),
            "metric": "customer evidence",
        },
        {
            "step": 4,
            "action": "Prepare incubation applications",
            "detail": (
                f"Review {program_count} program opportunities and verify "
                "current eligibility, cohort, deadline, funding and "
                "application requirements."
            ),
            "metric": "qualified applications",
        },
        {
            "step": 5,
            "action": "Review grants and non-dilutive options",
            "detail": (
                f"Review {grant_count} grant opportunities. Do not assume "
                "a grant is currently open or that the startup satisfies "
                "its eligibility criteria."
            ),
            "metric": "qualified grant applications",
        },
        {
            "step": 6,
            "action": "Build the investor pipeline",
            "detail": (
                f"Review {investor_count} investor opportunities and verify "
                "stage, geography, thesis, portfolio and current activity "
                "before contacting them."
            ),
            "metric": "qualified investor conversations",
        },
        {
            "step": 7,
            "action": "Pitch using evidence",
            "detail": (
                "Lead with the customer problem, observed evidence, product "
                "differentiation, traction and specific ask rather than a "
                "generic startup pitch."
            ),
            "metric": "reply / meeting / application rate",
        },
        {
            "step": 8,
            "action": "Track every opportunity",
            "detail": (
                "Move each opportunity through discovered, qualified, "
                "contacted, replied, meeting, application, diligence, "
                "won or rejected."
            ),
            "metric": "pipeline conversion",
        },
    ]


# ============================================================
# PIPELINE SPLIT + STATS
# ============================================================

def split_opportunities(opportunities: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "customers": [x for x in opportunities if x["kind"] == "customer"],
        "investors": [x for x in opportunities if x["kind"] == "investor"],
        "programs": [x for x in opportunities if x["kind"] == "program"],
        "grants": [x for x in opportunities if x["kind"] == "grant"],
        "partners": [x for x in opportunities if x["kind"] == "partner"],
        "resources": [x for x in opportunities if x["kind"] == "resource"],
    }


def pipeline_stats(opportunities: List[Dict[str, Any]]) -> Dict[str, Any]:
    buckets = split_opportunities(opportunities)
    return {
        "total": len(opportunities),
        "customers": len(buckets["customers"]),
        "investors": len(buckets["investors"]),
        "programs": len(buckets["programs"]),
        "grants": len(buckets["grants"]),
        "partners": len(buckets["partners"]),
        "high_priority": len([x for x in opportunities if x["priority"] == "high"]),
        "verified": len([
            x for x in opportunities
            if x["verification_status"] in {"VERIFIED", "STRONGLY_VERIFIED"}
        ]),
    }


# ============================================================
# MAIN RESEARCH PIPELINE
# ============================================================

async def search_web(
    query: str,
    adaptive: bool = True,
    limit: int = 25,
    budget_tier: str = "balanced",
    requested_mode: str = "auto",
    include_free_sources: bool = True,
    startup_for_pdf: Optional[StartupProfile] = None,
) -> Dict[str, Any]:

    query = query.strip()
    mode = detect_mode(query, requested_mode)
    budget = RequestBudget(budget_tier)
    geography = detect_geography(query)
    stage = detect_stage(query)
    categories = detect_categories(query)

    cache_key = hash_key(
        query, limit, budget_tier, adaptive, mode,
        include_free_sources,
        startup_for_pdf.company_name if startup_for_pdf else "",
    )
    cached = await cache_get("research", cache_key)
    if cached is not None:
        cached.setdefault("metadata", {})["cache_hit"] = True
        return cached

    # Static PDF catalog — zero API cost
    pdf_resources: List[Dict[str, Any]] = []
    if startup_for_pdf is not None:
        pdf_resources = pdf_sources_as_resources(
            startup_for_pdf,
            mode=mode,
            limit=25,
        )

    discovery_queries = build_mode_queries(query, mode, budget_tier)

    if include_free_sources:
        discovery_queries.extend(build_free_source_queries(query, mode))

    seen_query_keys = set()
    deduplicated = []
    for item in discovery_queries:
        key = normalize_text(item["query"])
        if key in seen_query_keys:
            continue
        seen_query_keys.add(key)
        deduplicated.append(item)
    discovery_queries = deduplicated

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

    async def limited_exa(item: Dict[str, str], adaptive_call: bool = False):
        async with semaphore:
            return await exa_search(item, budget, adaptive=adaptive_call)

    responses = await asyncio.gather(
        *[limited_exa(item) for item in discovery_queries],
        return_exceptions=True,
    )

    raw_results: List[Dict[str, Any]] = []
    for response in responses:
        if isinstance(response, list):
            raw_results.extend(response)

    candidates = merge_candidates(raw_results)

    tier_limits = {
        "cheap": (2, 2),
        "balanced": (MAX_DEEP_VERIFY, MAX_LIGHT_VERIFY),
        "deep": (MAX_DEEP_VERIFY, MAX_LIGHT_VERIFY),
    }
    deep_limit, light_limit = tier_limits.get(budget_tier, tier_limits["balanced"])

    deep_candidates = candidates[:deep_limit]
    light_candidates = candidates[deep_limit:deep_limit + light_limit]

    verified: List[Dict[str, Any]] = []

    async def verify(candidate: Dict[str, Any], depth: str):
        try:
            return await verify_candidate(candidate, query, budget, depth, mode)
        except Exception as exc:
            print(f"Verification failed for {candidate.get('name')}: {exc}")
            return None

    deep_results = await asyncio.gather(
        *[verify(c, "deep") for c in deep_candidates],
        return_exceptions=True,
    )
    verified.extend(
        r for r in deep_results
        if isinstance(r, dict) and r.get("name")
    )

    if len(verified) < min(limit, 8):
        light_results = await asyncio.gather(
            *[verify(c, "light") for c in light_candidates],
            return_exceptions=True,
        )
        verified.extend(
            r for r in light_results
            if isinstance(r, dict) and r.get("name")
        )

    adaptive_queries: List[Dict[str, str]] = []
    adaptive_raw: List[Dict[str, Any]] = []

    if (
        adaptive
        and budget.remaining.get("adaptive_exa", 0) > 0
        and len(verified) < min(limit, 8)
    ):
        strong = sorted(
            verified,
            key=lambda x: (x.get("evidence_score", 0), x.get("discovery_score", 0)),
            reverse=True,
        )[:4]

        for candidate in strong:
            name = candidate["name"]
            adaptive_queries.append({
                "category": (candidate.get("categories") or ["VC"])[0],
                "strategy": "adaptive_relationship",
                "query": f'"{name}" customers partners portfolio investors programs',
            })

        adaptive_responses = await asyncio.gather(
            *[limited_exa(item, adaptive_call=True) for item in adaptive_queries],
            return_exceptions=True,
        )
        for response in adaptive_responses:
            if isinstance(response, list):
                adaptive_raw.extend(response)

        adaptive_candidates = merge_candidates(adaptive_raw)
        existing_names = {item["normalized_name"] for item in verified}
        new_candidates = [
            c for c in adaptive_candidates
            if c["normalized_name"] not in existing_names
        ][:MAX_ADAPTIVE_VERIFY]

        adaptive_verified = await asyncio.gather(
            *[verify(c, "light") for c in new_candidates],
            return_exceptions=True,
        )
        verified.extend(
            r for r in adaptive_verified
            if isinstance(r, dict) and r.get("name")
        )

    entities: List[Dict[str, Any]] = []
    seen_names = set()
    for candidate in verified:
        entity = build_entity(candidate, query, mode)
        if not entity:
            continue
        if entity["normalized_name"] in seen_names:
            continue
        seen_names.add(entity["normalized_name"])
        entities.append(entity)

    entities.sort(
        key=lambda item: (item.get("final_score", 0), item.get("confidence", 0)),
        reverse=True,
    )
    entities = entities[:min(limit, 25)]

    resources = (
        match_free_sources(query, mode)
        if include_free_sources
        else []
    )

    metadata = {
        "query": query,
        "mode": mode,
        "geography": geography,
        "stage": stage,
        "categories": categories,
        "discovery_queries": len(discovery_queries),
        "raw_discovery_results": len(raw_results),
        "initial_candidates": len(candidates),
        "deep_verified": len(deep_candidates),
        "light_verified": len(light_candidates),
        "adaptive_queries": len(adaptive_queries),
        "adaptive_results": len(adaptive_raw),
        "verified_candidates": len(verified),
        "final_entities": len(entities),
        "adaptive_enabled": adaptive,
        "cache_hit": False,
        "budget": budget.snapshot(),
        "free_source_count": len(resources),
        "pdf_source_count": len(pdf_resources),
    }

    result = {
        "entities": entities,
        "resources": resources,
        "pdf_resources": pdf_resources,
        "metadata": metadata,
    }

    await cache_set("research", cache_key, result, SEARCH_CACHE_TTL)
    return result


# ============================================================
# RESEARCH QUERY (used by /api/research)
# ============================================================

async def research_query(
    query: str,
    adaptive: bool = True,
    limit: int = 25,
    budget_tier: str = "balanced",
    requested_mode: str = "auto",
    include_free_sources: bool = True,
    startup_for_pdf: Optional[StartupProfile] = None,
) -> Dict[str, Any]:

    result = await search_web(
        query, adaptive, limit, budget_tier,
        requested_mode, include_free_sources,
        startup_for_pdf=startup_for_pdf,
    )

    entities = result["entities"][:min(limit, 25)]
    resources = result.get("resources", [])
    pdf_resources = result.get("pdf_resources", [])
    mode = result["metadata"]["mode"]

    relationships = build_relationships(entities)
    actions = build_action_plan(
        startup_for_pdf or StartupProfile(product=query, description=query),
        [],
        resources + pdf_resources,
    )

    answer_parts = [
        f"Mode: {mode}",
        f"Found {len(entities)} relevant verified/researched targets.",
        f"Static fundraising sources matched: {len(pdf_resources)}",
        "",
        "Free-first resources:",
    ]
    for resource in resources[:8]:
        answer_parts.append(f"- {resource['name']} — {resource['description']}")

    if pdf_resources:
        answer_parts.append("")
        answer_parts.append("Fundraising / virtual-incubation sources (from catalog):")
        for r in pdf_resources[:15]:
            answer_parts.append(f"- {r['name']} — {r['url']}")

    answer_parts.extend(["", "Recommended workflow:"])
    for action in actions:
        answer_parts.append(f"{action['step']}. {action['action']} — {action['detail']}")

    return {
        "answer": "\n".join(answer_parts),
        "mode": mode,
        "entities": entities,
        "relationships": relationships,
        "connections": relationships,
        "resources": resources,
        "pdf_resources": pdf_resources,
        "opportunities": resources + pdf_resources,
        "investors": [
            e for e in entities
            if e.get("type") in {"VC", "ANGEL", "FAMILY_OFFICE", "LP"}
        ],
        "customers": [e for e in entities if e.get("type") == "CUSTOMER"],
        "programs": [
            e for e in entities
            if e.get("type") in {
                "ACCELERATOR", "INCUBATOR",
                "APPLICATION_PROGRAM", "GRANT",
            }
        ],
        "partners": [e for e in entities if e.get("type") == "PARTNER"],
        "actions": actions,
        "citations": [
            ev for entity in entities for ev in entity.get("evidence", [])
        ][:50],
        "providers": {"exa": True, "tavily": True},
        "stats": result["metadata"],
    }


# ============================================================
# API — HEALTH (called by frontend status badge)
# ============================================================

@app.get("/api/health")
async def health_check():

    await cache_cleanup()

    return {
        "status": "healthy",
        "version": APP_VERSION,
        "mode": "startup-intelligence-action-engine",
        "timestamp": now_iso(),
        "providers": {
            "exa": {
                "configured": bool(EXA_API_KEY),
                "role": "semantic discovery",
            },
            "tavily": {
                "configured": bool(TAVILY_API_KEY),
                "role": "selective evidence verification",
            },
        },
        "budgets": BUDGETS,
        "cache": {
            "path": CACHE_PATH,
            "search_ttl_seconds": SEARCH_CACHE_TTL,
            "profile_ttl_seconds": PROFILE_CACHE_TTL,
            "evidence_ttl_seconds": EVIDENCE_CACHE_TTL,
            "strategy_ttl_seconds": STRATEGY_CACHE_TTL,
        },
        "free_sources": len(FREE_SOURCE_CATALOG),
        "pdf_fundraising_sources": len(PDF_SOURCE_CATALOG),
        "pdf_catalog_stats": pdf_catalog_stats(),
        "capabilities": [
            "customer_acquisition",
            "customer_validation",
            "traction",
            "investor_discovery",
            "fundraising",
            "accelerator_discovery",
            "incubator_discovery",
            "grant_discovery",
            "relationship_graph",
            "free_first_resources",
            "pdf_fundraising_catalog",
        ],
    }


# ============================================================
# API — RESEARCH (called by frontend main form)
# ============================================================

@app.post("/api/research")
async def perform_research(request: ResearchRequest):

    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        results = await research_query(
            query,
            adaptive=request.adaptive,
            limit=request.limit,
            budget_tier=request.budget_tier,
            requested_mode=request.mode,
            include_free_sources=request.include_free_sources,
        )
        return {
            "research_run_id": str(uuid.uuid4()),
            "status": "completed",
            "results": {
                "query": query,
                "response": results,
                "sources": results.get("citations", []),
                "resources": results.get("resources", []),
                "fundraising_sources": results.get("pdf_resources", []),
            },
        }
    except Exception as exc:
        print(f"Research error: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Research pipeline failed. Check backend logs.",
        )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():
    return {
        "message": "Connecting the Dots AI",
        "version": APP_VERSION,
        "docs": "/docs",
        "health": "/api/health",
        "endpoints": {
            "health": "GET /api/health",
            "research": "POST /api/research",
        },
        "note": (
            "Only /api/health and /api/research are exposed because the "
            "frontend only calls these two endpoints."
        ),
    }


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )