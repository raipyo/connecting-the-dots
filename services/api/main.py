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
# CONNECTING THE DOTS AI v5
# ============================================================
# This version keeps the existing Exa -> candidate ranking ->
# Tavily verification architecture, but expands it into a startup
# intelligence workflow for:
#   1. TRACTION
#   2. IDEA_VALIDATION
#   3. FUNDRAISING
#   4. PITCHING
#   5. INVESTOR_DISCOVERY
#
# Important product principle:
# The engine does not treat every search result as an organization.
# It separates organizations, resources, signals, actions and evidence.
# This is especially useful for free fundraising resources shared on X,
# including the HarshEntrepre profile, while still discovering other
# public sources across the web.
# ============================================================

load_dotenv()

APP_VERSION = "5.0.0"

app = FastAPI(
    title="Connecting the Dots AI",
    version=APP_VERSION,
)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:3001,"
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

class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    user_id: Optional[str] = "anonymous"
    limit: int = Field(default=25, ge=1, le=25)
    adaptive: bool = True
    budget_tier: str = Field(default="balanced", pattern="^(cheap|balanced|deep)$")
    mode: str = Field(
        default="auto",
        pattern="^(auto|traction|validation|fundraising|pitching|investor_discovery)$",
    )
    include_free_sources: bool = True


class StrategyRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: str = Field(
        default="auto",
        pattern="^(auto|traction|validation|fundraising|pitching|investor_discovery)$",
    )
    budget_tier: str = Field(default="cheap", pattern="^(cheap|balanced|deep)$")


# ============================================================
# CONSTANTS
# ============================================================

CATEGORIES = [
    "VC", "ANGEL", "ACCELERATOR", "INCUBATOR",
    "FAMILY_OFFICE", "FOUNDATION", "LP", "GRANT",
    "CROWDFUNDING", "COMMUNITY", "CUSTOMER",
]

MODES = {
    "traction",
    "validation",
    "fundraising",
    "pitching",
    "investor_discovery",
}

EXA_MAX_RESULTS = 6
MAX_CANDIDATES = 50
MAX_DEEP_VERIFY = 8
MAX_LIGHT_VERIFY = 10
MAX_ADAPTIVE_VERIFY = 5
MAX_TAVILY_RESULTS = 3
MAX_CONCURRENT_SEARCHES = 6
EXA_TEXT_LIMIT = 3500
TAVILY_CONTENT_LIMIT = 4500
EVIDENCE_LIMIT = 1400

BUDGETS = {
    "cheap": {"exa": 8, "tavily": 8, "adaptive_exa": 0},
    "balanced": {"exa": 12, "tavily": 30, "adaptive_exa": 4},
    "deep": {"exa": 18, "tavily": 45, "adaptive_exa": 8},
}

SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL", "86400"))
PROFILE_CACHE_TTL = int(os.getenv("PROFILE_CACHE_TTL", "604800"))
EVIDENCE_CACHE_TTL = int(os.getenv("EVIDENCE_CACHE_TTL", "604800"))
STRATEGY_CACHE_TTL = int(os.getenv("STRATEGY_CACHE_TTL", "86400"))

CACHE_PATH = os.getenv(
    "CACHE_PATH",
    os.path.join("/tmp", "connecting_dots_cache.db"),
)


# ============================================================
# FREE / ORGANIC SOURCE CATALOG
# ============================================================
# These are intentionally modeled as resources, not fake "investors".
# A source can be free, partially free, application-based, or organic.
# The UI can explain the distinction instead of claiming that a source
# guarantees funding.
# ============================================================

FREE_SOURCE_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "harshentrepre-x",
        "name": "HarshEntrepre on X",
        "kind": "social_source",
        "mode": ["fundraising", "pitching", "traction", "validation"],
        "url": "https://x.com/HarshEntrepre",
        "free": True,
        "description": "Public founder/resource source to monitor for fundraising, startup ideas, team-building and ecosystem opportunities.",
        "query_templates": [
            'site:x.com/HarshEntrepre fundraising startup funding',
            'site:x.com/HarshEntrepre incubator accelerator funding',
            'site:x.com/HarshEntrepre grant startup founders',
            'site:x.com/HarshEntrepre pitch investor fundraising',
        ],
        "evidence_rule": "Treat individual posts as evidence only when the post itself is retrieved and dated.",
    },
    {
        "id": "openvc",
        "name": "OpenVC",
        "kind": "investor_platform",
        "mode": ["fundraising", "investor_discovery", "pitching"],
        "url": "https://www.openvc.app/",
        "free": True,
        "description": "Investor discovery and fundraising workflow with a free founder tier; premium features also exist.",
        "query_templates": [
            'site:openvc.app investors startup pre-seed seed',
            'site:openvc.app "free" startup fundraising',
        ],
        "evidence_rule": "Mark as free-core rather than universally free because OpenVC also has paid features.",
    },
    {
        "id": "yc",
        "name": "Y Combinator",
        "kind": "accelerator",
        "mode": ["fundraising", "pitching", "validation"],
        "url": "https://www.ycombinator.com/",
        "free": True,
        "description": "Accelerator and founder resources; application itself is a route to funding, not a guarantee of funding.",
        "query_templates": [
            'site:ycombinator.com apply startup accelerator funding',
            'site:ycombinator.com startup pitch advice',
            'site:ycombinator.com SAFE startup fundraising',
        ],
        "evidence_rule": "Separate application/resource availability from acceptance or investment outcomes.",
    },
    {
        "id": "f6s",
        "name": "F6S",
        "kind": "startup_program_platform",
        "mode": ["fundraising", "validation", "traction"],
        "url": "https://www.f6s.com/",
        "free": True,
        "description": "Startup program discovery platform useful for accelerators, grants and founder opportunities.",
        "query_templates": [
            'site:f6s.com startup grants accelerators funding',
            'site:f6s.com founder programs startup',
        ],
        "evidence_rule": "Verify each individual program's eligibility, fees and deadlines.",
    },
    {
        "id": "product-hunt",
        "name": "Product Hunt",
        "kind": "launch_community",
        "mode": ["traction", "validation", "pitching"],
        "url": "https://www.producthunt.com/",
        "free": True,
        "description": "Free launch/community channel for early adopters, feedback, social proof and distribution.",
        "query_templates": [
            'site:producthunt.com launch startup feedback validation',
            'site:producthunt.com/launch startup launch guide',
        ],
        "evidence_rule": "Use launch engagement as traction evidence, not as proof of product-market fit by itself.",
    },
    {
        "id": "reddit",
        "name": "Reddit communities",
        "kind": "community_signal",
        "mode": ["validation", "traction"],
        "url": "https://www.reddit.com/",
        "free": True,
        "description": "Community discussions can reveal pain points, objections, competitors and potential early users.",
        "query_templates": [
            'site:reddit.com startup idea validation customer pain',
            'site:reddit.com "would pay" problem startup',
        ],
        "evidence_rule": "Use multiple independent discussions and avoid treating anecdotes as market size.",
    },
    {
        "id": "hacker-news",
        "name": "Hacker News",
        "kind": "builder_community",
        "mode": ["validation", "traction"],
        "url": "https://news.ycombinator.com/",
        "free": True,
        "description": "Useful for technical products, founder feedback, Show HN launches and problem discovery.",
        "query_templates": [
            'site:news.ycombinator.com startup idea validation',
            'site:news.ycombinator.com "Show HN" startup',
        ],
        "evidence_rule": "Community feedback is a signal; it should be combined with user behavior and interviews.",
    },
    {
        "id": "github",
        "name": "GitHub",
        "kind": "open_source_signal",
        "mode": ["validation", "traction"],
        "url": "https://github.com/",
        "free": True,
        "description": "Useful for discovering open-source alternatives, contributor activity, issues and developer demand.",
        "query_templates": [
            'site:github.com startup open source alternative competitors',
            'site:github.com issues feature request developer pain',
        ],
        "evidence_rule": "Repository stars/issues are directional signals, not equivalent to customers or revenue.",
    },
]


# ============================================================
# FILTERS / QUERY TERMS
# ============================================================

NON_ORG_DOMAINS = {
    "linkedin.com", "medium.com", "reddit.com", "wikipedia.org",
    "crunchbase.com", "tracxn.com", "yourstory.com", "inc42.com",
    "techcrunch.com", "forbes.com", "economictimes.indiatimes.com",
    "economictimes.com", "moneycontrol.com", "x.com", "twitter.com",
    "producthunt.com", "news.ycombinator.com", "github.com",
    "openvc.app", "f6s.com", "ycombinator.com",
}

GENERIC_NAMES = {
    "venture capital", "venture capital firms", "venture capital investors",
    "venture capital funds", "vc funds", "vc investors", "seed investors",
    "seed funds", "angel investors", "investors in india", "startup investors",
    "startup funding", "investor directory", "investor list", "investment firms",
    "investment funds", "funding firms", "early stage investors", "investors",
    "investment companies", "venture firms", "fund managers", "startup funds",
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
    "LP": ["limited partner", "fund of funds", "institutional investor"],
    "GRANT": ["grant", "grant program", "non-dilutive"],
    "CROWDFUNDING": ["crowdfunding", "crowdinvesting", "crowd funding"],
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
            print(f"⚠️ Cache read failed: {exc}")
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
            print(f"⚠️ Cache write failed: {exc}")


async def cache_cleanup() -> None:
    async with _cache_lock:
        try:
            with sqlite3.connect(CACHE_PATH) as conn:
                conn.execute("DELETE FROM cache WHERE expires_at <= ?", (time.time(),))
                conn.commit()
        except Exception as exc:
            print(f"⚠️ Cache cleanup failed: {exc}")


# ============================================================
# BUDGET
# ============================================================

class RequestBudget:
    def __init__(self, tier: str):
        self.tier = tier if tier in BUDGETS else "balanced"
        config = BUDGETS[self.tier]
        self.remaining = dict(config)
        self.used = {key: 0 for key in config}
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
        return host[4:] if host.startswith("www.") else host
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


# ============================================================
# INTENT UNDERSTANDING
# ============================================================

def detect_mode(query: str, requested_mode: str = "auto") -> str:
    if requested_mode != "auto":
        return requested_mode
    q = normalize_text(query)
    patterns = [
        ("fundraising", ["fundraising", "raise money", "raise capital", "funding", "investor", "grant", "accelerator", "incubator", "vc", "angel"]),
        ("pitching", ["pitch deck", "pitch", "investor outreach", "cold email", "fundraising deck"]),
        ("validation", ["validate", "validation", "idea validation", "customer discovery", "market validation", "problem validation", "would pay"]),
        ("traction", ["traction", "customers", "growth", "users", "distribution", "launch", "early adopters", "go to market"]),
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
        ("United States", ["united states", "usa", "us startups", "american startups"]),
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
        "CROWDFUNDING": ["crowdfunding", "crowdinvesting"],
    }
    found = [category for category, terms in aliases.items() if any(term in q for term in terms)]
    return found or ["VC", "ANGEL", "ACCELERATOR", "INCUBATOR", "GRANT"]


# ============================================================
# QUERY BUILDING
# ============================================================

def build_mode_queries(user_query: str, mode: str, budget_tier: str) -> List[Dict[str, str]]:
    geography = detect_geography(user_query)
    stage = detect_stage(user_query)
    categories = detect_categories(user_query)
    queries: List[Dict[str, str]] = []

    if mode == "traction":
        queries.extend([
            {"category": "COMMUNITY", "strategy": "distribution", "query": f'"{user_query}" early adopters community launch users'},
            {"category": "COMMUNITY", "strategy": "feedback", "query": f'"{user_query}" customer feedback complaints alternatives'},
            {"category": "CUSTOMER", "strategy": "demand", "query": f'"{user_query}" customers buying demand market'},
            {"category": "COMMUNITY", "strategy": "social", "query": f'"{user_query}" traction founders users X community'},
        ])
    elif mode == "validation":
        queries.extend([
            {"category": "CUSTOMER", "strategy": "pain", "query": f'"{user_query}" customer pain problem complaints'},
            {"category": "CUSTOMER", "strategy": "alternatives", "query": f'"{user_query}" alternatives competitors customers'},
            {"category": "CUSTOMER", "strategy": "willingness_to_pay", "query": f'"{user_query}" "would pay" OR "pay for"'},
            {"category": "COMMUNITY", "strategy": "community", "query": f'"{user_query}" Reddit Hacker News customer discussion'},
        ])
    elif mode == "pitching":
        queries.extend([
            {"category": "VC", "strategy": "pitch", "query": f'"{user_query}" startup pitch deck investor'},
            {"category": "VC", "strategy": "outreach", "query": f'"{user_query}" investor outreach cold email'},
            {"category": "VC", "strategy": "thesis", "query": f'"{user_query}" investment thesis {geography} {stage}'},
        ])
    elif mode == "fundraising":
        queries.extend([
            {"category": "GRANT", "strategy": "grant", "query": f'"{geography}" startup grant {stage} non-dilutive'},
            {"category": "ACCELERATOR", "strategy": "accelerator", "query": f'"{geography}" startup accelerator {stage} funding'},
            {"category": "INCUBATOR", "strategy": "incubator", "query": f'"{geography}" startup incubator funding {stage}'},
            {"category": "VC", "strategy": "investor", "query": f'"{geography}" "{stage}" startup venture capital investor'},
            {"category": "ANGEL", "strategy": "angel", "query": f'"{geography}" "{stage}" startup angel investor'},
            {"category": "FAMILY_OFFICE", "strategy": "family_office", "query": f'"{geography}" family office startup investment {stage}'},
            {"category": "CROWDFUNDING", "strategy": "crowdfunding", "query": f'"{geography}" startup crowdfunding equity crowdfunding'},
            {"category": "COMMUNITY", "strategy": "free_resources", "query": f'"{user_query}" free fundraising resources startup founders'},
        ])
    else:
        for category in categories:
            if category == "VC":
                strategies = [
                    ("direct", f'"{geography}" "venture capital" "{stage}" startups'),
                    ("portfolio", f'"{geography}" VC portfolio startups "{stage}"'),
                    ("thesis", f'"{geography}" "investment thesis" "{stage}" "venture capital"'),
                ]
            elif category == "ANGEL":
                strategies = [
                    ("direct", f'"{geography}" angel investor "{stage}" startups'),
                    ("network", f'"{geography}" angel network startup investment'),
                ]
            elif category == "ACCELERATOR":
                strategies = [("program", f'"{geography}" startup accelerator funding "{stage}"')]
            elif category == "INCUBATOR":
                strategies = [("program", f'"{geography}" startup incubator funding "{stage}"')]
            elif category == "GRANT":
                strategies = [("grant", f'"{geography}" startup grant "{stage}" non-dilutive')]
            else:
                strategies = [("direct", f'"{geography}" {category.lower()} startup investment "{stage}"')]
            for strategy, built_query in strategies:
                queries.append({"category": category, "strategy": strategy, "query": built_query})

    max_queries = {"cheap": 8, "balanced": 14, "deep": 20}.get(budget_tier, 14)
    seen: Set[str] = set()
    output: List[Dict[str, str]] = []
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

async def exa_search(item: Dict[str, str], budget: RequestBudget, adaptive: bool = False) -> List[Dict[str, Any]]:
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
        for result in getattr(response, "results", []) or []:
            url = canonical_url(getattr(result, "url", "") or "")
            if not url:
                continue
            output.append({
                "title": (getattr(result, "title", "") or "")[:300],
                "content": (getattr(result, "text", "") or "")[:EXA_TEXT_LIMIT],
                "url": url,
                "author": (getattr(result, "author", "") or "")[:200],
                "published_date": getattr(result, "published_date", "") or "",
                "provider": "exa",
                "category": item["category"],
                "strategy": item["strategy"],
                "search_query": item["query"],
                "score": float(getattr(result, "score", 0) or 0),
            })
        await cache_set("search", cache_key, output, SEARCH_CACHE_TTL)
        return output
    except Exception as exc:
        print(f"⚠️ Exa failed: {exc}")
        return []


async def tavily_search(query: str, category: str, purpose: str, budget: RequestBudget) -> List[Dict[str, Any]]:
    cache_key = hash_key(query, category, purpose, MAX_TAVILY_RESULTS)
    cached = await cache_get("evidence", cache_key)
    if cached is not None:
        return cached
    if not await budget.consume("tavily"):
        return []
    try:
        response = await asyncio.to_thread(
            tavily_client.search,
            query=query,
            search_depth="advanced",
            max_results=MAX_TAVILY_RESULTS,
            include_answer=False,
            include_raw_content=False,
        )
        results = []
        for item in response.get("results", []) or []:
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
        print(f"⚠️ Tavily failed: {exc}")
        return []


# ============================================================
# ORGANIZATION / ENTITY EXTRACTION
# ============================================================

def clean_organization_name(name: str) -> str:
    name = re.sub(r"^[\s\-–—|:;,]+", "", (name or "").strip())
    name = re.sub(r"[\s\-–—|:;,]+$", "", name)
    name = re.split(
        r"\s+(?:is|are|was|were|has|have|provides|offers|invests|invested|investing|backs|backed|focuses|specializes)\b",
        name,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"\s+", " ", name).strip(" -–—|:;,." )


def looks_generic(name: str) -> bool:
    normalized = normalize_name(name)
    if not normalized or normalized in GENERIC_NAMES or normalized in GENERIC_TOKENS:
        return True
    return any(re.search(pattern, normalized) for pattern in [
        r"^top\s+", r"^best\s+", r"^list\s+of\s+", r"^ranking",
        r"^guide\b", r"^directory\b", r"^how\s+to\b", r"^who\s+",
        r"^investors?\s+in\s+", r"^venture\s+capital\s+firms?",
        r"^angel\s+investors?", r"\bin\s+india$", r"\bfor\s+startups$",
    ])


def is_valid_organization(name: str) -> bool:
    name = clean_organization_name(name)
    if not name or looks_generic(name):
        return False
    if len(name) < 2 or len(name) > 100 or len(name.split()) > 8:
        return False
    return not name.endswith((".", "?", "!"))


def is_listicle(title: str) -> bool:
    title = normalize_text(title)
    if not title:
        return True
    return any(re.search(pattern, title) for pattern in [
        r"^top\s+", r"^best\s+", r"list\s+of", r"ranking", r"directory",
        r"\bguide\b", "investors in india", "venture capital firms",
        "startup investors", "angel investors", r"\b20\d{2}\b",
    ])


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
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)\s+(?:is|are)\s+(?:a|an|the)\s+(?:venture capital|venture|investment|angel|accelerator|incubator|family office|foundation)\b",
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)\s+(?:invests|invested|investing)\s+(?:in|into)\b",
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)\s+(?:backs|backed|backing)\b",
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)\s+(?:portfolio|portfolio companies)\b",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, combined, flags=re.IGNORECASE):
            candidate = clean_organization_name(match if isinstance(match, str) else match[0])
            if is_valid_organization(candidate):
                return candidate
    text = normalize_text(combined)
    if any(term in text for term in ["invests", "portfolio", "venture capital", "angel investor", "accelerator", "incubator", "family office", "foundation"]):
        candidate = domain_brand(url)
        if is_valid_organization(candidate):
            return candidate
    return None


# ============================================================
# CANDIDATE MERGING / SCORING
# ============================================================

def result_relevance_score(result: Dict[str, Any]) -> float:
    title = normalize_text(result.get("title", ""))
    content = normalize_text(result.get("content", ""))
    domain = domain_from_url(result.get("url", ""))
    score = min(0.35, max(0.0, float(result.get("score", 0) or 0)) * 0.35)
    if domain and domain not in NON_ORG_DOMAINS:
        score += 0.20
    if any(term in title for term in ["portfolio", "investment", "investor", "ventures", "capital", "accelerator", "incubator"]):
        score += 0.15
    if any(term in content for term in ["we invest", "our portfolio", "our investments", "investment thesis", "we back"]):
        score += 0.20
    if is_listicle(title):
        score -= 0.20
    return max(0.0, min(1.0, score))


def merge_candidates(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}
    seen_urls: Set[str] = set()
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
        candidate["best_discovery_score"] = max(candidate["best_discovery_score"], result_relevance_score(result))

    output = []
    for candidate in candidates.values():
        candidate["categories"] = sorted(candidate["categories"])
        candidate["strategies"] = sorted(candidate["strategies"])
        candidate["domains"] = sorted(candidate["domains"])
        candidate["discovery_score"] = round(min(1.0,
            candidate["best_discovery_score"] * 0.60
            + min(1.0, candidate["discovery_count"] / 4) * 0.25
            + min(1.0, len(candidate["strategies"]) / 3) * 0.10
            + min(1.0, len(candidate["domains"]) / 2) * 0.05
        ), 3)
        output.append(candidate)
    output.sort(key=lambda x: (x["discovery_score"], x["discovery_count"]), reverse=True)
    return output[:MAX_CANDIDATES]


# ============================================================
# EVIDENCE
# ============================================================

def build_evidence_queries(candidate: Dict[str, Any], user_query: str, depth: str, mode: str) -> List[Tuple[str, str]]:
    name = candidate["name"]
    geography = detect_geography(user_query)
    stage = detect_stage(user_query)
    category = (candidate.get("categories") or ["VC"])[0]

    if mode == "validation":
        queries = [
            (f'"{name}" customers reviews complaints', "customer_signal"),
            (f'"{name}" users traction adoption', "traction"),
        ]
    elif mode == "traction":
        queries = [
            (f'"{name}" customers users growth', "customer_signal"),
            (f'"{name}" launch traction community', "distribution"),
        ]
    elif category == "GRANT":
        queries = [
            (f'"{name}" grant eligibility application', "grant"),
            (f'"{name}" startup funding deadline', "funding"),
        ]
    elif category == "LP":
        queries = [
            (f'"{name}" limited partner venture capital fund', "lp_relationship"),
            (f'"{name}" committed to venture capital fund', "fund_commitment"),
        ]
    else:
        queries = [
            (f'"{name}" "{geography}" "{stage}" startups investment', "investment"),
            (f'"{name}" portfolio startups', "portfolio"),
            (f'"{name}" investment thesis "{geography}"', "thesis"),
        ]
    return queries[:1] if depth == "light" else queries


def evidence_signals(text: str, category: str, user_query: str, mode: str) -> Dict[str, float]:
    text = normalize_text(text)
    geography = normalize_text(detect_geography(user_query))
    stage = normalize_text(detect_stage(user_query))
    signals = {
        "investment": 0.0, "geography": 0.0, "stage": 0.0,
        "portfolio": 0.0, "transaction": 0.0, "official": 0.0,
        "category": 0.0, "traction": 0.0, "customer": 0.0,
        "free_resource": 0.0, "contradiction": 0.0,
    }
    if any(term in text for term in ["invests", "invested", "investing", "investment", "backs", "backed"]):
        signals["investment"] = 1.0
    if any(term in text for term in [geography, geography.replace(" ", "")]):
        signals["geography"] = 1.0
    stage_terms = {"pre-seed": ["pre-seed", "pre seed"], "seed": ["seed stage", "seed-stage", "seed round"], "early stage": ["early stage", "early-stage"], "series a": ["series a"]}.get(stage, [stage])
    if any(term in text for term in stage_terms):
        signals["stage"] = 1.0
    if any(term in text for term in ["portfolio", "portfolio company", "portfolio companies"]):
        signals["portfolio"] = 1.0
    if any(term in text for term in ["funding round", "seed round", "series a", "investment round", "raised $", "raised usd"]):
        signals["transaction"] = 1.0
    if any(term in text for term in ["our portfolio", "our investments", "we invest", "we back", "investment thesis", "about us"]):
        signals["official"] = 1.0
    if any(term in text for term in CATEGORY_TERMS.get(category, [])):
        signals["category"] = 1.0
    if any(term in text for term in ["users", "customers", "adoption", "growth", "traction", "revenue"]):
        signals["traction"] = 1.0
    if any(term in text for term in ["customer", "customers", "pain point", "problem", "complaint", "review"]):
        signals["customer"] = 1.0
    if any(term in text for term in ["free", "no cost", "no fee", "free to apply", "free forever"]):
        signals["free_resource"] = 1.0
    if any(term in text for term in ["does not invest", "do not invest", "no longer invests", "not an investor"]):
        signals["contradiction"] = 1.0
    return signals


def source_quality(result: Dict[str, Any]) -> float:
    url = result.get("url", "")
    title = normalize_text(result.get("title", ""))
    content = normalize_text(result.get("content", ""))
    domain = domain_from_url(url)
    score = 0.0
    if domain and domain not in NON_ORG_DOMAINS:
        score += 0.30
    if any(term in content for term in ["we invest", "our portfolio", "our investments", "investment thesis", "we back", "official"]):
        score += 0.35
    if any(term in title for term in ["portfolio", "investment", "thesis", "funding", "grant"]):
        score += 0.15
    if not is_listicle(title):
        score += 0.10
    if result.get("provider") == "tavily":
        score += 0.05
    return min(score, 1.0)


async def verify_candidate(candidate: Dict[str, Any], user_query: str, budget: RequestBudget, depth: str, mode: str) -> Dict[str, Any]:
    category = (candidate.get("categories") or ["VC"])[0]
    profile_key = hash_key(candidate["normalized_name"], category, detect_geography(user_query), detect_stage(user_query), depth, mode)
    cached = await cache_get("profile", profile_key)
    if cached is not None:
        return cached

    queries = build_evidence_queries(candidate, user_query, depth, mode)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

    async def run(query: str, purpose: str) -> List[Dict[str, Any]]:
        async with semaphore:
            return await tavily_search(query, category, purpose, budget)

    responses = await asyncio.gather(*[run(query, purpose) for query, purpose in queries], return_exceptions=True)
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
        if current is None or float(item.get("score", 0) or 0) > float(current.get("score", 0) or 0):
            unique_sources[url] = item
    evidence = list(unique_sources.values())

    aggregated = {key: 0.0 for key in [
        "investment", "geography", "stage", "portfolio", "transaction", "official",
        "category", "traction", "customer", "free_resource", "contradiction",
    ]}
    domains: Set[str] = set()
    evidence_items: List[Dict[str, Any]] = []
    quality_scores: List[float] = []

    for item in evidence:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        signals = evidence_signals(text, category, user_query, mode)
        quality = source_quality(item)
        quality_scores.append(quality)
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
            "search_query": item.get("search_query", ""),
            "signals": signals,
        })

    diversity = min(1.0, len(domains) / 3)
    average_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

    if mode in {"traction", "validation"}:
        evidence_score = (
            aggregated["customer"] * 0.22
            + aggregated["traction"] * 0.24
            + aggregated["geography"] * 0.10
            + aggregated["official"] * 0.10
            + diversity * 0.12
            + average_quality * 0.07
            + aggregated["category"] * 0.05
            - aggregated["contradiction"] * 0.25
        )
    elif mode == "fundraising":
        evidence_score = (
            aggregated["investment"] * 0.20
            + aggregated["transaction"] * 0.12
            + aggregated["free_resource"] * 0.12
            + aggregated["stage"] * 0.10
            + aggregated["geography"] * 0.10
            + aggregated["official"] * 0.12
            + aggregated["category"] * 0.08
            + diversity * 0.09
            + average_quality * 0.07
            - aggregated["contradiction"] * 0.25
        )
    else:
        evidence_score = (
            aggregated["investment"] * 0.24
            + aggregated["geography"] * 0.12
            + aggregated["stage"] * 0.12
            + aggregated["portfolio"] * 0.12
            + aggregated["transaction"] * 0.10
            + aggregated["official"] * 0.10
            + aggregated["category"] * 0.08
            + diversity * 0.07
            + average_quality * 0.05
            - aggregated["contradiction"] * 0.25
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
    }.get(category, "INVESTOR_TO_STARTUP")

    verified = {
        **candidate,
        "evidence": sorted(evidence_items, key=lambda x: x.get("quality", 0), reverse=True)[:5],
        "evidence_signals": aggregated,
        "evidence_score": evidence_score,
        "source_diversity": round(diversity, 3),
        "average_source_quality": round(average_quality, 3),
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
        relevance = 0.55
        if any(token in q for token in ["fund", "invest", "raise", "grant", "pitch", "accelerator", "incubator"]):
            if "fundraising" in source["mode"]:
                relevance += 0.25
        if any(token in q for token in ["traction", "customer", "user", "growth", "launch"]):
            if "traction" in source["mode"]:
                relevance += 0.20
        if any(token in q for token in ["validate", "idea", "problem", "feedback"]):
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
                "category": "FREE_SOURCE",
                "strategy": source["id"],
                "query": template,
                "source_id": source["id"],
            })
    return output[:8]


# ============================================================
# ADAPTIVE DISCOVERY
# ============================================================

def build_adaptive_queries(candidates: List[Dict[str, Any]], user_query: str, mode: str) -> List[Dict[str, str]]:
    stage = detect_stage(user_query)
    geography = detect_geography(user_query)
    strong = sorted(candidates, key=lambda x: (x.get("evidence_score", 0), x.get("discovery_score", 0)), reverse=True)[:4]
    queries = []
    for candidate in strong:
        name = candidate["name"]
        category = (candidate.get("categories") or ["VC"])[0]
        queries.append({
            "category": category,
            "strategy": "related_entities",
            "query": f'"{name}" partners portfolio customers "{geography}"',
        })
        if mode == "fundraising":
            queries.append({
                "category": category,
                "strategy": "co_investor",
                "query": f'"{name}" co-investors "{stage}" startup',
            })
        elif mode in {"traction", "validation"}:
            queries.append({
                "category": "CUSTOMER",
                "strategy": "customer_signal",
                "query": f'"{name}" users customers reviews alternatives',
            })
    return queries


# ============================================================
# FINAL ENTITY / RESOURCE OBJECTS
# ============================================================

def calculate_final_score(candidate: Dict[str, Any]) -> float:
    discovery = float(candidate.get("discovery_score", 0) or 0)
    evidence = float(candidate.get("evidence_score", 0) or 0)
    diversity = float(candidate.get("source_diversity", 0) or 0)
    quality = float(candidate.get("average_source_quality", 0) or 0)
    count = min(1.0, float(candidate.get("discovery_count", 0) or 0) / 4)
    score = discovery * 0.15 + evidence * 0.60 + diversity * 0.10 + quality * 0.05 + count * 0.10
    if candidate.get("verification_status") == "STRONGLY_VERIFIED":
        score += 0.05
    if candidate.get("verification_status") == "WEAK":
        score -= 0.15
    return round(max(0.0, min(score, 0.99)), 3)


def build_entity(candidate: Dict[str, Any], user_query: str, mode: str) -> Optional[Dict[str, Any]]:
    name = candidate.get("name", "")
    if not is_valid_organization(name):
        return None
    final_score = calculate_final_score(candidate)
    if final_score < 0.30:
        return None
    category = (candidate.get("categories") or ["INVESTOR"])[0]
    signals = candidate.get("evidence_signals", {})
    stage = detect_stage(user_query) if signals.get("stage") else "Unknown"
    confidence = min(0.99, final_score + (0.05 if candidate.get("verification_status") == "STRONGLY_VERIFIED" else 0))
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, normalize_name(name))),
        "name": name,
        "normalized_name": normalize_name(name),
        "type": category,
        "country": detect_geography(user_query),
        "stage": stage,
        "mode": mode,
        "relationship": candidate.get("relationship", "INVESTOR_TO_STARTUP"),
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
        "final_score": final_score,
        "providers": ["exa", "tavily"],
        "source": "Exa + Tavily",
        "search_query": user_query,
    }


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
        else:
            target_name = f"{entity.get('stage', 'Early Stage')} Startup"
        target_id = str(uuid.uuid5(uuid.NAMESPACE_URL, normalize_name(f"{target_type}:{target_name}")))
        relationships.append({
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{entity['id']}:{relationship}:{target_id}")),
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
# STRATEGY ENGINE
# ============================================================

def build_action_plan(query: str, mode: str, resources: List[Dict[str, Any]], entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    if mode == "fundraising":
        actions = [
            {"step": 1, "action": "Validate the fundraising target", "detail": "Define stage, geography, sector, round size and the investor problem-fit before outreach."},
            {"step": 2, "action": "Use free-first channels", "detail": "Start with public/free-core resources and accelerator/grant applications before paying for databases."},
            {"step": 3, "action": "Build an evidence-backed investor list", "detail": "Connect investor thesis, geography, stage, portfolio and recent activity."},
            {"step": 4, "action": "Prepare a proof package", "detail": "Combine product demo, customer evidence, traction, market insight and a concise pitch deck."},
            {"step": 5, "action": "Run measured outreach", "detail": "Track contact, response, meeting, diligence and next-step signals instead of sending mass messages."},
        ]
    elif mode == "validation":
        actions = [
            {"step": 1, "action": "Extract the customer problem", "detail": "Collect repeated complaints, workarounds and existing alternatives."},
            {"step": 2, "action": "Find real conversations", "detail": "Use public communities and discussion threads as leads for interviews."},
            {"step": 3, "action": "Test willingness to act", "detail": "Look for signups, demo requests, preorders, pilots or other observable behavior."},
            {"step": 4, "action": "Record objections", "detail": "Turn objections into product hypotheses rather than treating positive comments as validation."},
        ]
    elif mode == "traction":
        actions = [
            {"step": 1, "action": "Choose one distribution loop", "detail": "Pick a repeatable channel such as communities, content, partnerships or product-led referrals."},
            {"step": 2, "action": "Launch a measurable experiment", "detail": "Define an audience, message, landing page and measurable conversion event."},
            {"step": 3, "action": "Capture proof", "detail": "Collect active users, retention, conversions, testimonials and customer outcomes."},
            {"step": 4, "action": "Feed results back into validation", "detail": "Use behavior to update the target customer and product positioning."},
        ]
    elif mode == "pitching":
        actions = [
            {"step": 1, "action": "Create a one-sentence thesis", "detail": "State customer, painful problem, product and why now."},
            {"step": 2, "action": "Lead with evidence", "detail": "Put customer proof and traction before broad market claims."},
            {"step": 3, "action": "Match the investor", "detail": "Tie the pitch to documented stage, geography, sector and portfolio fit."},
            {"step": 4, "action": "Make the ask explicit", "detail": "State round size, instrument if known, milestones and use of funds."},
        ]
    else:
        actions = [
            {"step": 1, "action": "Clarify the target relationship", "detail": "Decide whether you need customers, investors, partners, talent or validation."},
            {"step": 2, "action": "Map entities", "detail": "Use the graph to connect organizations, communities, programs and evidence."},
            {"step": 3, "action": "Verify before acting", "detail": "Prioritize primary sources and recent evidence for decisions."},
        ]
    actions.append({
        "step": len(actions) + 1,
        "action": "Review free sources first",
        "detail": f"Matched {len(resources)} free/core resources for this mode; verify each program's current eligibility before applying.",
    })
    return actions


def calculate_traction(entities: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not entities:
        return {"discovered": 0, "verified": 0, "strongly_verified": 0, "verification_rate": 0, "average_confidence": 0, "category_coverage": {}}
    verified = [e for e in entities if e.get("verification_status") in {"VERIFIED", "STRONGLY_VERIFIED"}]
    strong = [e for e in entities if e.get("verification_status") == "STRONGLY_VERIFIED"]
    categories: Dict[str, int] = {}
    for entity in entities:
        category = entity.get("type", "UNKNOWN")
        categories[category] = categories.get(category, 0) + 1
    return {
        "discovered": len(entities),
        "verified": len(verified),
        "strongly_verified": len(strong),
        "verification_rate": round(len(verified) / len(entities), 3),
        "average_confidence": round(sum(e.get("confidence", 0) for e in entities) / len(entities), 3),
        "category_coverage": categories,
    }


# ============================================================
# MAIN RESEARCH PIPELINE
# ============================================================

async def search_web(query: str, adaptive: bool = True, limit: int = 25, budget_tier: str = "balanced", requested_mode: str = "auto", include_free_sources: bool = True) -> Dict[str, Any]:
    query = query.strip()
    mode = detect_mode(query, requested_mode)
    budget = RequestBudget(budget_tier)
    geography = detect_geography(query)
    stage = detect_stage(query)
    categories = detect_categories(query)

    cache_key = hash_key(query, limit, budget_tier, adaptive, mode, include_free_sources)
    cached = await cache_get("research", cache_key)
    if cached is not None:
        cached.setdefault("metadata", {})["cache_hit"] = True
        return cached

    discovery_queries = build_mode_queries(query, mode, budget_tier)
    if include_free_sources:
        discovery_queries.extend(build_free_source_queries(query, mode))

    # Deduplicate provider queries.
    seen_query_keys = set()
    discovery_queries = [
        item for item in discovery_queries
        if not (normalize_text(item["query"]) in seen_query_keys or seen_query_keys.add(normalize_text(item["query"])))
    ]

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

    async def limited_exa(item: Dict[str, str], adaptive_call: bool = False):
        async with semaphore:
            return await exa_search(item, budget, adaptive=adaptive_call)

    responses = await asyncio.gather(*[limited_exa(item) for item in discovery_queries], return_exceptions=True)
    raw_results: List[Dict[str, Any]] = []
    for response in responses:
        if isinstance(response, list):
            raw_results.extend(response)

    candidates = merge_candidates(raw_results)
    tier_limits = {"cheap": (2, 4), "balanced": (MAX_DEEP_VERIFY, MAX_LIGHT_VERIFY), "deep": (MAX_DEEP_VERIFY, MAX_LIGHT_VERIFY)}
    deep_limit, light_limit = tier_limits.get(budget_tier, tier_limits["balanced"])
    deep_candidates = candidates[:deep_limit]
    light_candidates = candidates[deep_limit:deep_limit + light_limit]

    verified: List[Dict[str, Any]] = []

    async def verify(candidate: Dict[str, Any], depth: str):
        try:
            return await verify_candidate(candidate, query, budget, depth, mode)
        except Exception as exc:
            print(f"⚠️ Verification failed for {candidate.get('name')}: {exc}")
            return None

    deep_results = await asyncio.gather(*[verify(candidate, "deep") for candidate in deep_candidates], return_exceptions=True)
    verified.extend(result for result in deep_results if isinstance(result, dict) and result.get("name"))

    if len(verified) < min(limit, 10):
        light_results = await asyncio.gather(*[verify(candidate, "light") for candidate in light_candidates], return_exceptions=True)
        verified.extend(result for result in light_results if isinstance(result, dict) and result.get("name"))

    adaptive_queries: List[Dict[str, str]] = []
    adaptive_raw: List[Dict[str, Any]] = []
    if adaptive and budget.remaining.get("adaptive_exa", 0) > 0 and len(verified) < min(limit, 10):
        adaptive_queries = build_adaptive_queries(verified, query, mode)
        adaptive_responses = await asyncio.gather(*[limited_exa(item, adaptive_call=True) for item in adaptive_queries], return_exceptions=True)
        for response in adaptive_responses:
            if isinstance(response, list):
                adaptive_raw.extend(response)
        adaptive_candidates = merge_candidates(adaptive_raw)
        existing_names = {item["normalized_name"] for item in verified}
        new_candidates = [c for c in adaptive_candidates if c["normalized_name"] not in existing_names][:MAX_ADAPTIVE_VERIFY]
        adaptive_verified = await asyncio.gather(*[verify(c, "light") for c in new_candidates], return_exceptions=True)
        verified.extend(result for result in adaptive_verified if isinstance(result, dict) and result.get("name"))

    entities: List[Dict[str, Any]] = []
    seen_names: Set[str] = set()
    for candidate in verified:
        entity = build_entity(candidate, query, mode)
        if not entity:
            continue
        if entity["normalized_name"] in seen_names:
            continue
        seen_names.add(entity["normalized_name"])
        entities.append(entity)

    entities.sort(key=lambda item: (item.get("final_score", 0), item.get("confidence", 0)), reverse=True)
    entities = entities[:min(limit, 25)]

    resources = match_free_sources(query, mode) if include_free_sources else []
    traction = calculate_traction(entities)
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
    }
    result = {"entities": entities, "resources": resources, "metadata": metadata}
    await cache_set("research", cache_key, result, SEARCH_CACHE_TTL)
    return result


async def research_query(query: str, adaptive: bool = True, limit: int = 25, budget_tier: str = "balanced", requested_mode: str = "auto", include_free_sources: bool = True) -> Dict[str, Any]:
    result = await search_web(query, adaptive, limit, budget_tier, requested_mode, include_free_sources)
    entities = result["entities"][:min(limit, 25)]
    resources = result.get("resources", [])
    mode = result["metadata"]["mode"]
    relationships = build_relationships(entities)
    traction = calculate_traction(entities)
    actions = build_action_plan(query, mode, resources, entities)

    answer_parts = [
        f"Mode: {mode}",
        f"Found {len(entities)} verified/relevant entities for \"{query}\".",
        "",
        "Free-first resources:",
    ]
    for resource in resources[:8]:
        answer_parts.append(f"- {resource['name']} — {resource['description']}")
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
        "opportunities": resources,
        "investors": [e for e in entities if e.get("type") in {"VC", "ANGEL", "FAMILY_OFFICE", "LP"}],
        "actions": actions,
        "citations": [ev for entity in entities for ev in entity.get("evidence", [])][:50],
        "providers": {"exa": True, "tavily": True},
        "stats": {**result["metadata"], **traction},
    }


# ============================================================
# API
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
            },
        }
    except Exception as exc:
        print(f"❌ Research error: {exc}")
        raise HTTPException(status_code=500, detail="Research pipeline failed. Check backend logs for details.")


@app.post("/api/strategy")
async def strategy(request: StrategyRequest):
    results = await research_query(
        request.query.strip(),
        adaptive=False,
        limit=15,
        budget_tier=request.budget_tier,
        requested_mode=request.mode,
        include_free_sources=True,
    )
    return {
        "query": request.query.strip(),
        "mode": results["mode"],
        "resources": results["resources"],
        "actions": results["actions"],
        "entities": results["entities"],
        "stats": results["stats"],
    }


@app.get("/api/resources")
async def resources(mode: str = "fundraising", query: str = "startup"):
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported mode: {mode}")
    matched = match_free_sources(query, mode)
    return {"query": query, "mode": mode, "count": len(matched), "resources": matched}


@app.get("/api/entities/search")
async def search_entities(query: str, limit: int = 10, budget_tier: str = "cheap", mode: str = "investor_discovery"):
    query = (query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    limit = max(1, min(limit, MAX_CANDIDATES))
    result = await search_web(query, adaptive=False, limit=limit, budget_tier=budget_tier, requested_mode=mode, include_free_sources=False)
    entities = result["entities"][:limit]
    return {
        "query": query,
        "mode": result["metadata"]["mode"],
        "entities": entities,
        "count": len(entities),
        "providers": {"exa": True, "tavily": True},
        "traction": calculate_traction(entities),
        "stats": result["metadata"],
    }


@app.delete("/api/cache")
async def clear_cache():
    async with _cache_lock:
        try:
            with sqlite3.connect(CACHE_PATH) as conn:
                conn.execute("DELETE FROM cache")
                conn.commit()
            return {"status": "cleared"}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not clear cache: {exc}")


@app.get("/api/health")
async def health_check():
    await cache_cleanup()
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "mode": "startup-intelligence-free-first",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "providers": {
            "exa": {"configured": bool(EXA_API_KEY), "role": "semantic discovery"},
            "tavily": {"configured": bool(TAVILY_API_KEY), "role": "targeted evidence verification"},
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
    }


@app.get("/")
async def root():
    return {
        "message": "Connecting the Dots AI",
        "version": APP_VERSION,
        "docs": "/docs",
        "health": "/api/health",
        "capabilities": [
            "traction",
            "idea_validation",
            "fundraising",
            "pitching",
            "investor_discovery",
            "free_source_discovery",
            "relationship_graph",
        ],
        "pipeline": "intent -> free-source matching -> Exa discovery -> entity resolution -> targeted Tavily verification -> adaptive discovery -> confidence -> actions -> relationship graph",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
