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
# CONFIG
# ============================================================

load_dotenv()

app = FastAPI(
    title="Connecting the Dots AI",
    version="4.0.0",
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


# ============================================================
# API KEYS
# ============================================================

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
EXA_API_KEY = os.getenv("EXA_API_KEY")

if not TAVILY_API_KEY:
    raise RuntimeError("TAVILY_API_KEY is not configured.")

if not EXA_API_KEY:
    raise RuntimeError("EXA_API_KEY is not configured.")


# ============================================================
# CLIENTS
# ============================================================

tavily_client = TavilyClient(api_key=TAVILY_API_KEY)
exa_client = Exa(api_key=EXA_API_KEY)


# ============================================================
# REQUEST MODELS
# ============================================================

class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    user_id: Optional[str] = "anonymous"

    # Final number requested by the frontend.
    limit: int = Field(default=25, ge=1, le=25)

    # Adaptive discovery is deliberately conservative.
    adaptive: bool = True

    # Lets expensive searches be disabled for cheap previews.
    budget_tier: str = Field(default="balanced", pattern="^(cheap|balanced|deep)$")


# ============================================================
# CONSTANTS
# ============================================================

CATEGORIES = [
    "VC",
    "ANGEL",
    "ACCELERATOR",
    "INCUBATOR",
    "FAMILY_OFFICE",
    "FOUNDATION",
    "LP",
]

# Exa = cheap/fast discovery.
EXA_MAX_RESULTS = 6

# Candidate pool can be larger than the verification pool.
MAX_CANDIDATES = 40

# Only a small number get expensive Tavily verification.
MAX_DEEP_VERIFY = 8
MAX_LIGHT_VERIFY = 10
MAX_ADAPTIVE_VERIFY = 5

# Tavily is intentionally smaller than the previous implementation.
MAX_TAVILY_RESULTS = 3

# Hard per-request provider budgets.
# Cache hits do NOT consume budget.
BUDGETS = {
    "cheap": {
        "exa": 8,
        "tavily": 8,
        "adaptive_exa": 0,
    },
    "balanced": {
        "exa": 12,
        "tavily": 30,
        "adaptive_exa": 4,
    },
    "deep": {
        "exa": 18,
        "tavily": 45,
        "adaptive_exa": 8,
    },
}

# Keep network concurrency bounded.
MAX_CONCURRENT_SEARCHES = 6

# Text limits prevent huge pages from entering scoring/caches.
EXA_TEXT_LIMIT = 3500
TAVILY_CONTENT_LIMIT = 4500
TAVILY_RAW_LIMIT = 6000
EVIDENCE_LIMIT = 1200

# Cache TTL.
SEARCH_CACHE_TTL = int(os.getenv("SEARCH_CACHE_TTL", "86400"))          # 1 day
PROFILE_CACHE_TTL = int(os.getenv("PROFILE_CACHE_TTL", "604800"))       # 7 days
EVIDENCE_CACHE_TTL = int(os.getenv("EVIDENCE_CACHE_TTL", "604800"))     # 7 days

CACHE_PATH = os.getenv(
    "CACHE_PATH",
    os.path.join("/tmp", "connecting_dots_cache.db"),
)


# ============================================================
# GENERIC / ARTICLE FILTERS
# ============================================================

GENERIC_NAMES = {
    "venture capital",
    "venture capital firms",
    "venture capital investors",
    "venture capital funds",
    "vc funds",
    "vc investors",
    "seed investors",
    "seed funds",
    "angel investors",
    "angel investors in india",
    "investors in india",
    "startup investors",
    "startup funding",
    "investor directory",
    "investor list",
    "investment firms",
    "investment funds",
    "funding firms",
    "venture investors",
    "early stage investors",
    "early-stage investors",
    "accelerators in india",
    "startup accelerators in india",
    "startup incubators in india",
    "investors",
    "investment companies",
    "venture firms",
    "fund managers",
    "startup funds",
    "venture capital company",
    "investment company",
}

GENERIC_TOKENS = {
    "top",
    "best",
    "list",
    "guide",
    "directory",
    "ranking",
    "rankings",
    "investors",
    "funding",
    "startups",
    "investment",
    "companies",
}

NON_ORG_DOMAINS = {
    "linkedin.com",
    "medium.com",
    "reddit.com",
    "wikipedia.org",
    "crunchbase.com",
    "tracxn.com",
    "yourstory.com",
    "inc42.com",
    "techcrunch.com",
    "forbes.com",
    "economictimes.indiatimes.com",
    "economictimes.com",
    "moneycontrol.com",
}

CATEGORY_TERMS = {
    "VC": ["venture capital", "venture fund", "venture investor"],
    "ANGEL": ["angel investor", "angel network", "angel fund"],
    "ACCELERATOR": ["accelerator", "accelerator program"],
    "INCUBATOR": ["incubator", "incubation"],
    "FAMILY_OFFICE": ["family office"],
    "FOUNDATION": ["foundation", "impact investor"],
    "LP": ["limited partner", "fund of funds", "institutional investor"],
}


# ============================================================
# SMALL SQLITE CACHE
# ============================================================
#
# This gives local development a persistent cache without adding
# another dependency. On Vercel/serverless, /tmp is ephemeral.
# For production persistence, replace this with Redis/Postgres.
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
            "CREATE INDEX IF NOT EXISTS idx_cache_expiry "
            "ON cache(expires_at)"
        )
        conn.commit()


_init_cache()


async def cache_get(
    cache_type: str,
    key: str,
) -> Optional[Any]:
    cache_key = f"{cache_type}:{key}"

    async with _cache_lock:
        try:
            with sqlite3.connect(CACHE_PATH) as conn:
                row = conn.execute(
                    """
                    SELECT expires_at, value
                    FROM cache
                    WHERE cache_key = ?
                    """,
                    (cache_key,),
                ).fetchone()

                if not row:
                    return None

                expires_at, value = row

                if expires_at <= time.time():
                    conn.execute(
                        "DELETE FROM cache WHERE cache_key = ?",
                        (cache_key,),
                    )
                    conn.commit()
                    return None

                return json.loads(value)

        except Exception as exc:
            print(f"⚠️ Cache read failed: {exc}")
            return None


async def cache_set(
    cache_type: str,
    key: str,
    value: Any,
    ttl: int,
) -> None:
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
                conn.execute(
                    "DELETE FROM cache WHERE expires_at <= ?",
                    (time.time(),),
                )
                conn.commit()
        except Exception as exc:
            print(f"⚠️ Cache cleanup failed: {exc}")


# ============================================================
# REQUEST BUDGET
# ============================================================

class RequestBudget:
    def __init__(self, tier: str):
        config = BUDGETS.get(tier, BUDGETS["balanced"])

        self.tier = tier if tier in BUDGETS else "balanced"
        self.remaining = {
            "exa": config["exa"],
            "tavily": config["tavily"],
            "adaptive_exa": config["adaptive_exa"],
        }
        self.used = {
            "exa": 0,
            "tavily": 0,
            "adaptive_exa": 0,
        }
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
    if value is None:
        return ""

    return re.sub(r"\s+", " ", str(value).lower()).strip()


def normalize_name(value: str) -> str:
    value = normalize_text(value)

    value = re.sub(
        r"[^a-z0-9\s&]",
        " ",
        value,
    )

    return re.sub(r"\s+", " ", value).strip()


def normalize_url(url: str) -> str:
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        host = (parsed.hostname or "").lower()
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

        scheme = parsed.scheme.lower() or "https"
        host = (parsed.hostname or "").lower()

        if host.startswith("www."):
            host = host[4:]

        path = re.sub(r"/+$", "", parsed.path or "/")

        # Remove tracking/query parameters.
        return urlunparse(
            (
                scheme,
                host,
                path,
                "",
                "",
                "",
            )
        )

    except Exception:
        return ""


def domain_from_url(url: str) -> str:
    return normalize_url(url)


def hash_key(*parts: Any) -> str:
    payload = "||".join(
        normalize_text(str(part))
        for part in parts
    )

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


# ============================================================
# ORGANIZATION VALIDATION
# ============================================================

def clean_organization_name(name: str) -> str:
    if not name:
        return ""

    name = re.sub(
        r"^[\s\-–—|:;,]+",
        "",
        name.strip(),
    )

    name = re.sub(
        r"[\s\-–—|:;,]+$",
        "",
        name,
    )

    # Prevent regex extraction from swallowing an entire sentence.
    name = re.split(
        r"\s+(?:is|are|was|were|has|have|provides|offers|"
        r"invests|invested|investing|backs|backed|"
        r"focuses|focus|specializes)\b",
        name,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    name = re.sub(r"\s+", " ", name)

    return name.strip(" -–—|:;,.")


def looks_generic(name: str) -> bool:
    normalized = normalize_name(name)

    if not normalized:
        return True

    if normalized in GENERIC_NAMES:
        return True

    if normalized in GENERIC_TOKENS:
        return True

    patterns = [
        r"^top\s+",
        r"^best\s+",
        r"^list\s+of\s+",
        r"^ranking",
        r"^guide\b",
        r"^directory\b",
        r"^how\s+to\b",
        r"^where\s+to\b",
        r"^who\s+",
        r"^investors?\s+in\s+",
        r"^venture\s+capital\s+firms?",
        r"^venture\s+capital\s+investors?",
        r"^venture\s+capital\s+funds?",
        r"^seed\s+investors?",
        r"^seed\s+funds?",
        r"^angel\s+investors?",
        r"^startup\s+investors?",
        r"^investment\s+firms?",
        r"\bin\s+india$",
        r"\bfor\s+startups$",
    ]

    return any(
        re.search(pattern, normalized)
        for pattern in patterns
    )


def is_valid_organization(name: str) -> bool:
    name = clean_organization_name(name)

    if not name:
        return False

    if looks_generic(name):
        return False

    if len(name) < 2 or len(name) > 100:
        return False

    words = name.split()

    if len(words) > 8:
        return False

    # Reject obvious prose.
    if name.endswith((".", "?", "!")):
        return False

    return True


def is_listicle(title: str) -> bool:
    title = normalize_text(title)

    if not title:
        return True

    patterns = [
        r"^top\s+",
        r"^best\s+",
        r"list\s+of",
        r"ranking",
        r"rankings",
        r"directory",
        r"\bguide\b",
        "investors in india",
        "venture capital firms",
        "startup investors",
        "angel investors",
        "funds investing",
        "firms investing",
        r"\b20\d{2}\b",
    ]

    return any(
        re.search(pattern, title)
        for pattern in patterns
    )


# ============================================================
# QUERY UNDERSTANDING
# ============================================================

def detect_geography(query: str) -> str:
    q = normalize_text(query)

    geography_aliases = [
        ("United Arab Emirates", [
            "united arab emirates",
            "uae",
        ]),
        ("India", [
            "india",
            "indian",
        ]),
        ("Singapore", [
            "singapore",
        ]),
        ("United Kingdom", [
            "united kingdom",
            "uk",
            "britain",
        ]),
        ("United States", [
            "united states",
            "usa",
            "us startups",
            "american startups",
        ]),
    ]

    for geography, aliases in geography_aliases:
        if any(alias in q for alias in aliases):
            return geography

    # Existing product focus is India, so retain that default.
    return "India"


def detect_stage(query: str) -> str:
    q = normalize_text(query)

    if "pre-seed" in q or "pre seed" in q:
        return "pre-seed"

    if "seed stage" in q or "seed-stage" in q:
        return "seed"

    if re.search(r"\bseed\b", q):
        return "seed"

    if "series a" in q:
        return "Series A"

    if "early stage" in q or "early-stage" in q:
        return "early stage"

    return "early stage"


def detect_categories(query: str) -> List[str]:
    q = normalize_text(query)
    padded = f" {q} "

    aliases = {
        "VC": [
            " vc ",
            "venture capital",
            "venture capital firms",
            "venture funds",
        ],
        "ANGEL": [
            "angel",
            "angel investor",
            "angel investors",
        ],
        "ACCELERATOR": [
            "accelerator",
            "accelerators",
        ],
        "INCUBATOR": [
            "incubator",
            "incubators",
        ],
        "FAMILY_OFFICE": [
            "family office",
            "family offices",
        ],
        "FOUNDATION": [
            "foundation",
            "foundations",
            "impact investor",
        ],
        "LP": [
            " lp ",
            "limited partner",
            "limited partners",
            "fund of funds",
        ],
    }

    categories = [
        category
        for category, terms in aliases.items()
        if any(term in padded for term in terms)
    ]

    return categories or CATEGORIES.copy()


# ============================================================
# DISCOVERY QUERIES
# ============================================================

def build_discovery_queries(
    user_query: str,
    budget_tier: str = "balanced",
) -> List[Dict[str, str]]:
    geography = detect_geography(user_query)
    stage = detect_stage(user_query)
    categories = detect_categories(user_query)

    queries: List[Dict[str, str]] = []

    # Preserve the user's actual intent instead of replacing it
    # with hardcoded "India" queries.
    for category in categories:
        if category == "VC":
            strategies = [
                (
                    "direct",
                    f'"{geography}" '
                    f'"venture capital" "{stage}" startups',
                ),
                (
                    "portfolio",
                    f'"{geography}" '
                    f'VC portfolio startups "{stage}"',
                ),
                (
                    "thesis",
                    f'"{geography}" '
                    f'"investment thesis" "{stage}" '
                    f'"venture capital"',
                ),
            ]

        elif category == "ANGEL":
            strategies = [
                (
                    "direct",
                    f'"{geography}" angel investor '
                    f'"{stage}" startups',
                ),
                (
                    "portfolio",
                    f'"{geography}" angel network '
                    f'portfolio startup investment',
                ),
            ]

        elif category == "ACCELERATOR":
            strategies = [
                (
                    "program",
                    f'"{geography}" startup accelerator '
                    f'investment "{stage}"',
                ),
                (
                    "portfolio",
                    f'"{geography}" accelerator '
                    f'portfolio startup investment',
                ),
            ]

        elif category == "INCUBATOR":
            strategies = [
                (
                    "program",
                    f'"{geography}" startup incubator '
                    f'investment "{stage}"',
                ),
                (
                    "portfolio",
                    f'"{geography}" incubator '
                    f'portfolio startups funding',
                ),
            ]

        elif category == "FAMILY_OFFICE":
            strategies = [
                (
                    "direct",
                    f'"{geography}" family office '
                    f'startup investment "{stage}"',
                ),
                (
                    "portfolio",
                    f'"{geography}" family office '
                    f'venture portfolio startups',
                ),
            ]

        elif category == "FOUNDATION":
            strategies = [
                (
                    "impact",
                    f'"{geography}" foundation '
                    f'impact startup investment',
                ),
                (
                    "portfolio",
                    f'"{geography}" foundation '
                    f'social enterprise portfolio',
                ),
            ]

        else:  # LP
            strategies = [
                (
                    "fund",
                    f'"{geography}" limited partner '
                    f'venture capital fund',
                ),
                (
                    "institutional",
                    f'"{geography}" institutional investor '
                    f'venture capital funds',
                ),
                (
                    "fund-of-funds",
                    f'"{geography}" fund of funds '
                    f'venture capital startup ecosystem',
                ),
            ]

        for strategy, query in strategies:
            queries.append({
                "category": category,
                "strategy": strategy,
                "query": query,
            })

    # Cheap tier deliberately uses fewer queries.
    max_queries = {
        "cheap": 8,
        "balanced": 12,
        "deep": 18,
    }.get(budget_tier, 12)

    seen = set()
    unique = []

    for item in queries:
        key = normalize_text(item["query"])

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

        if len(unique) >= max_queries:
            break

    return unique


# ============================================================
# EXA DISCOVERY
# ============================================================

async def exa_search(
    item: Dict[str, str],
    budget: RequestBudget,
    adaptive: bool = False,
) -> List[Dict[str, Any]]:
    provider_budget = "adaptive_exa" if adaptive else "exa"

    cache_key = hash_key(
        item["query"],
        EXA_MAX_RESULTS,
        EXA_TEXT_LIMIT,
    )

    cached = await cache_get("search", cache_key)

    if cached is not None:
        return cached

    if not await budget.consume(provider_budget):
        print(f"🛑 Exa budget exhausted: {provider_budget}")
        return []

    query = item["query"]

    print(
        f"🟣 Exa [{item['category']}/"
        f"{item['strategy']}]: {query}"
    )

    try:
        response = await asyncio.to_thread(
            exa_client.search,
            query,
            type="auto",
            num_results=EXA_MAX_RESULTS,
            contents={
                "text": {
                    "max_characters": EXA_TEXT_LIMIT,
                }
            },
        )

        output = []

        for result in getattr(response, "results", []) or []:
            url = getattr(result, "url", "") or ""

            if not url:
                continue

            canonical = canonical_url(url)

            if not canonical:
                continue

            output.append({
                "title": (
                    getattr(result, "title", "") or ""
                )[:300],
                "content": (
                    getattr(result, "text", "") or ""
                )[:EXA_TEXT_LIMIT],
                "url": canonical,
                "author": (
                    getattr(result, "author", "") or ""
                )[:200],
                "published_date": (
                    getattr(result, "published_date", "") or ""
                ),
                "provider": "exa",
                "category": item["category"],
                "strategy": item["strategy"],
                "search_query": query,
                "score": float(
                    getattr(result, "score", 0) or 0
                ),
            })

        await cache_set(
            "search",
            cache_key,
            output,
            SEARCH_CACHE_TTL,
        )

        return output

    except Exception as exc:
        print(f"⚠️ Exa failed: {exc}")
        return []


# ============================================================
# TAVILY VERIFICATION
# ============================================================

async def tavily_search(
    query: str,
    category: str,
    purpose: str,
    budget: RequestBudget,
) -> List[Dict[str, Any]]:
    cache_key = hash_key(
        query,
        category,
        purpose,
        MAX_TAVILY_RESULTS,
    )

    cached = await cache_get("evidence", cache_key)

    if cached is not None:
        return cached

    if not await budget.consume("tavily"):
        print("🛑 Tavily budget exhausted.")
        return []

    print(
        f"🔵 Tavily [{category}/{purpose}]: {query}"
    )

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
            url = item.get("url", "") or ""

            if not url:
                continue

            results.append({
                "title": (
                    item.get("title", "") or ""
                )[:300],
                "content": (
                    item.get("content", "") or ""
                )[:TAVILY_CONTENT_LIMIT],
                "url": canonical_url(url),
                "score": float(
                    item.get("score", 0) or 0
                ),
                "provider": "tavily",
                "category": category,
                "purpose": purpose,
                "search_query": query,
            })

        await cache_set(
            "evidence",
            cache_key,
            results,
            EVIDENCE_CACHE_TTL,
        )

        return results

    except Exception as exc:
        print(f"⚠️ Tavily failed: {exc}")
        return []


# ============================================================
# ORGANIZATION EXTRACTION
# ============================================================

def domain_brand(url: str) -> str:
    domain = domain_from_url(url)

    if not domain:
        return ""

    first = domain.split(".")[0]

    if first in {
        "blog",
        "news",
        "about",
        "app",
        "mail",
        "www",
    }:
        return ""

    return (
        first
        .replace("-", " ")
        .replace("_", " ")
        .title()
    )


def title_brand(title: str) -> str:
    if not title:
        return ""

    # Common formats:
    # "Firm Name | Investment Thesis"
    # "Firm Name - Portfolio"
    # "Firm Name: About"
    candidate = re.split(
        r"\s+[|:\-–—]\s+",
        title,
        maxsplit=1,
    )[0].strip()

    candidate = clean_organization_name(candidate)

    if is_valid_organization(candidate):
        return candidate

    return ""


def extract_organization(
    result: Dict[str, Any],
) -> Optional[str]:
    title = result.get("title", "")
    content = result.get("content", "")
    url = result.get("url", "")

    # Strongest cheap signal: title of a direct organization page.
    if title and not is_listicle(title):
        candidate = title_brand(title)

        if candidate:
            return candidate

    combined = (
        f"{title}\n"
        f"{content[:EXA_TEXT_LIMIT]}"
    )

    patterns = [
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)"
        r"\s+(?:is|are)\s+(?:a|an|the)\s+"
        r"(?:venture capital|venture|investment|"
        r"angel|startup|accelerator|incubator|"
        r"family office|foundation)\b",

        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)"
        r"\s+(?:invests|invested|investing)"
        r"\s+(?:in|into)\b",

        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)"
        r"\s+(?:backs|backed|backing)\b",

        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)"
        r"\s+(?:portfolio|portfolio companies)\b",
    ]

    for pattern in patterns:
        for match in re.findall(
            pattern,
            combined,
            flags=re.IGNORECASE,
        ):
            candidate = clean_organization_name(
                match if isinstance(match, str) else match[0]
            )

            if is_valid_organization(candidate):
                return candidate

    # Domain fallback is only accepted if the page contains
    # actual investment/category signals.
    text = normalize_text(combined)

    investment_signal = any(
        term in text
        for term in [
            "invests",
            "invested",
            "investing",
            "portfolio",
            "venture capital",
            "angel investor",
            "startup investment",
            "accelerator",
            "incubator",
            "family office",
            "foundation",
        ]
    )

    if investment_signal:
        candidate = domain_brand(url)

        if is_valid_organization(candidate):
            return candidate

    return None


# ============================================================
# CANDIDATE MERGING / RESOLUTION
# ============================================================

def result_relevance_score(
    result: Dict[str, Any],
) -> float:
    title = normalize_text(result.get("title", ""))
    content = normalize_text(result.get("content", ""))
    domain = domain_from_url(result.get("url", ""))

    score = 0.0

    # Preserve provider relevance when available.
    score += min(
        0.35,
        max(0.0, float(result.get("score", 0) or 0)) * 0.35,
    )

    if domain and domain not in NON_ORG_DOMAINS:
        score += 0.20

    if any(
        term in title
        for term in [
            "portfolio",
            "investment",
            "investor",
            "ventures",
            "capital",
            "accelerator",
            "incubator",
        ]
    ):
        score += 0.15

    if any(
        term in content
        for term in [
            "we invest",
            "our portfolio",
            "our investments",
            "investment thesis",
            "we back",
        ]
    ):
        score += 0.20

    if is_listicle(title):
        score -= 0.20

    return max(0.0, min(1.0, score))


def merge_candidates(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}

    # Deduplicate URLs before entity resolution.
    seen_urls: Set[str] = set()

    for result in results:
        url = canonical_url(result.get("url", ""))

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        organization = extract_organization(result)

        if not organization:
            continue

        normalized = normalize_name(organization)

        if not normalized:
            continue

        if normalized not in candidates:
            candidates[normalized] = {
                "name": organization,
                "normalized_name": normalized,
                "results": [],
                "categories": set(),
                "strategies": set(),
                "domains": set(),
                "discovery_count": 0,
                "best_discovery_score": 0.0,
            }

        candidate = candidates[normalized]

        candidate["results"].append(result)

        category = result.get(
            "category",
            "UNKNOWN",
        )

        strategy = result.get(
            "strategy",
            "unknown",
        )

        candidate["categories"].add(category)
        candidate["strategies"].add(strategy)

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
        candidate["categories"] = sorted(
            candidate["categories"]
        )
        candidate["strategies"] = sorted(
            candidate["strategies"]
        )
        candidate["domains"] = sorted(
            candidate["domains"]
        )

        # Multiple independent discovery strategies are useful,
        # but do not allow raw frequency to dominate quality.
        candidate["discovery_score"] = round(
            min(
                1.0,
                candidate["best_discovery_score"] * 0.60
                + min(
                    1.0,
                    candidate["discovery_count"] / 4,
                ) * 0.25
                + min(
                    1.0,
                    len(candidate["strategies"]) / 3,
                ) * 0.10
                + min(
                    1.0,
                    len(candidate["domains"]) / 2,
                ) * 0.05,
            ),
            3,
        )

        output.append(candidate)

    output.sort(
        key=lambda x: (
            x["discovery_score"],
            x["discovery_count"],
        ),
        reverse=True,
    )

    return output[:MAX_CANDIDATES]


# ============================================================
# EVIDENCE QUERIES
# ============================================================

def build_evidence_queries(
    candidate: Dict[str, Any],
    user_query: str,
    depth: str,
) -> List[Tuple[str, str]]:
    name = candidate["name"]
    geography = detect_geography(user_query)
    stage = detect_stage(user_query)

    category = (
        candidate.get("categories") or ["VC"]
    )[0]

    if category == "LP":
        queries = [
            (
                f'"{name}" limited partner '
                f'venture capital fund',
                "lp_relationship",
            ),
            (
                f'"{name}" committed to '
                f'venture capital fund',
                "fund_commitment",
            ),
        ]
    else:
        queries = [
            (
                f'"{name}" "{geography}" '
                f'"{stage}" startups investment',
                "investment",
            ),
            (
                f'"{name}" portfolio startups',
                "portfolio",
            ),
            (
                f'"{name}" investment thesis '
                f'"{geography}"',
                "thesis",
            ),
        ]

    if depth == "light":
        return queries[:1]

    return queries


# ============================================================
# EVIDENCE ANALYSIS
# ============================================================

def evidence_signals(
    text: str,
    category: str,
    user_query: str,
) -> Dict[str, float]:
    text = normalize_text(text)
    geography = normalize_text(
        detect_geography(user_query)
    )
    stage = normalize_text(
        detect_stage(user_query)
    )

    signals = {
        "investment": 0.0,
        "geography": 0.0,
        "stage": 0.0,
        "portfolio": 0.0,
        "transaction": 0.0,
        "official": 0.0,
        "category": 0.0,
        "contradiction": 0.0,
    }

    if any(
        term in text
        for term in [
            "invests",
            "invested",
            "investing",
            "investment",
            "investments",
            "backs",
            "backed",
        ]
    ):
        signals["investment"] = 1.0

    geography_terms = {
        "india": ["india", "indian startup", "indian startups"],
        "united arab emirates": ["uae", "united arab emirates"],
        "singapore": ["singapore"],
        "united kingdom": ["uk", "united kingdom", "british"],
        "united states": ["usa", "united states", "american startup"],
    }.get(geography, [geography])

    if any(term in text for term in geography_terms):
        signals["geography"] = 1.0

    stage_terms = {
        "pre-seed": ["pre-seed", "pre seed"],
        "seed": ["seed stage", "seed-stage", "seed round"],
        "early stage": ["early stage", "early-stage", "early-stage startup"],
        "series a": ["series a"],
    }.get(stage, [stage])

    if any(term in text for term in stage_terms):
        signals["stage"] = 1.0

    if any(
        term in text
        for term in [
            "portfolio",
            "portfolio company",
            "portfolio companies",
        ]
    ):
        signals["portfolio"] = 1.0

    if any(
        term in text
        for term in [
            "led the round",
            "led a",
            "participated in",
            "funding round",
            "seed round",
            "series a",
            "investment round",
        ]
    ):
        signals["transaction"] = 1.0

    if any(
        term in text
        for term in [
            "our portfolio",
            "our investments",
            "we invest",
            "we back",
            "investment thesis",
            "about us",
        ]
    ):
        signals["official"] = 1.0

    if any(
        term in text
        for term in CATEGORY_TERMS.get(category, [])
    ):
        signals["category"] = 1.0

    if any(
        term in text
        for term in [
            "does not invest",
            "do not invest",
            "no longer invests",
            "not an investor",
            "not a venture fund",
        ]
    ):
        signals["contradiction"] = 1.0

    return signals


def source_quality(
    result: Dict[str, Any],
) -> float:
    url = result.get("url", "")
    title = normalize_text(
        result.get("title", "")
    )
    content = normalize_text(
        result.get("content", "")
    )
    domain = domain_from_url(url)

    score = 0.0

    if domain:
        if domain not in NON_ORG_DOMAINS:
            score += 0.30

    if any(
        term in content
        for term in [
            "we invest",
            "our portfolio",
            "our investments",
            "investment thesis",
            "we back",
        ]
    ):
        score += 0.35

    if "portfolio" in title:
        score += 0.15

    if "investment" in title or "thesis" in title:
        score += 0.10

    if not is_listicle(title):
        score += 0.10

    if result.get("provider") == "tavily":
        score += 0.05

    return min(score, 1.0)


# ============================================================
# VERIFY CANDIDATE
# ============================================================

async def verify_candidate(
    candidate: Dict[str, Any],
    user_query: str,
    budget: RequestBudget,
    depth: str = "deep",
) -> Dict[str, Any]:
    category = (
        candidate.get("categories") or ["VC"]
    )[0]

    profile_key = hash_key(
        candidate["normalized_name"],
        category,
        detect_geography(user_query),
        detect_stage(user_query),
        depth,
    )

    cached = await cache_get(
        "profile",
        profile_key,
    )

    if cached is not None:
        return cached

    queries = build_evidence_queries(
        candidate,
        user_query,
        depth,
    )

    semaphore = asyncio.Semaphore(
        MAX_CONCURRENT_SEARCHES
    )

    async def run(
        query: str,
        purpose: str,
    ) -> List[Dict[str, Any]]:
        async with semaphore:
            return await tavily_search(
                query=query,
                category=category,
                purpose=purpose,
                budget=budget,
            )

    responses = await asyncio.gather(
        *[
            run(query, purpose)
            for query, purpose in queries
        ],
        return_exceptions=True,
    )

    evidence: List[Dict[str, Any]] = []

    for response in responses:
        if isinstance(response, Exception):
            continue

        evidence.extend(response)

    # URL-level dedupe.
    unique_sources: Dict[str, Dict[str, Any]] = {}

    for item in evidence:
        url = canonical_url(
            item.get("url", "")
        )

        if not url:
            continue

        # Keep the highest scoring result for a URL.
        current = unique_sources.get(url)

        if (
            current is None
            or float(item.get("score", 0) or 0)
            > float(current.get("score", 0) or 0)
        ):
            unique_sources[url] = item

    evidence = list(
        unique_sources.values()
    )

    aggregated = {
        "investment": 0.0,
        "geography": 0.0,
        "stage": 0.0,
        "portfolio": 0.0,
        "transaction": 0.0,
        "official": 0.0,
        "category": 0.0,
        "contradiction": 0.0,
    }

    domains: Set[str] = set()
    evidence_items: List[Dict[str, Any]] = []
    quality_scores: List[float] = []

    for item in evidence:
        text = " ".join([
            item.get("title", ""),
            item.get("content", ""),
        ])

        signals = evidence_signals(
            text,
            category,
            user_query,
        )

        quality = source_quality(item)
        quality_scores.append(quality)

        domain = domain_from_url(
            item.get("url", "")
        )

        if domain:
            domains.add(domain)

        for key in aggregated:
            aggregated[key] = max(
                aggregated[key],
                signals[key],
            )

        evidence_items.append({
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "content": (
                item.get("content", "") or ""
            )[:EVIDENCE_LIMIT],
            "quality": round(quality, 3),
            "search_query": item.get(
                "search_query",
                "",
            ),
            "signals": signals,
        })

    # Independent-domain diversity.
    diversity_score = min(
        1.0,
        len(domains) / 3,
    )

    # Average quality gives source quality a bounded influence.
    average_quality = (
        sum(quality_scores) / len(quality_scores)
        if quality_scores
        else 0.0
    )

    evidence_score = (
        aggregated["investment"] * 0.20
        + aggregated["geography"] * 0.14
        + aggregated["stage"] * 0.12
        + aggregated["portfolio"] * 0.14
        + aggregated["transaction"] * 0.10
        + aggregated["official"] * 0.10
        + aggregated["category"] * 0.08
        + diversity_score * 0.07
        + average_quality * 0.05
        - aggregated["contradiction"] * 0.25
    )

    evidence_score = round(
        max(
            0.0,
            min(
                1.0,
                evidence_score,
            ),
        ),
        3,
    )

    if category == "LP":
        relationship = "LP_TO_FUND"
    elif category == "ACCELERATOR":
        relationship = "ACCELERATOR_TO_STARTUP"
    elif category == "INCUBATOR":
        relationship = "INCUBATOR_TO_STARTUP"
    else:
        relationship = "INVESTOR_TO_STARTUP"

    if evidence_score >= 0.70:
        status = "STRONGLY_VERIFIED"
    elif evidence_score >= 0.50:
        status = "VERIFIED"
    elif evidence_score >= 0.35:
        status = "SUPPORTED"
    else:
        status = "WEAK"

    verified = {
        **candidate,
        "evidence": sorted(
            evidence_items,
            key=lambda item: item.get(
                "quality",
                0,
            ),
            reverse=True,
        )[:5],
        "evidence_signals": aggregated,
        "evidence_score": evidence_score,
        "source_diversity": round(
            diversity_score,
            3,
        ),
        "average_source_quality": round(
            average_quality,
            3,
        ),
        "source_count": len(evidence),
        "domain_count": len(domains),
        "relationship": relationship,
        "verification_status": status,
        "verification_score": evidence_score,
        "verification_depth": depth,
    }

    await cache_set(
        "profile",
        profile_key,
        verified,
        PROFILE_CACHE_TTL,
    )

    return verified


# ============================================================
# ADAPTIVE DISCOVERY
# ============================================================

def build_adaptive_queries(
    candidates: List[Dict[str, Any]],
    user_query: str,
) -> List[Dict[str, str]]:
    stage = detect_stage(user_query)
    geography = detect_geography(user_query)

    strong = sorted(
        candidates,
        key=lambda x: (
            x.get("evidence_score", 0),
            x.get("discovery_score", 0),
        ),
        reverse=True,
    )[:4]

    queries: List[Dict[str, str]] = []

    for candidate in strong:
        name = candidate["name"]
        category = (
            candidate.get("categories") or ["VC"]
        )[0]

        queries.append({
            "category": category,
            "strategy": "co-investor",
            "query": (
                f'"{name}" co-investors '
                f'"{geography}" startup'
            ),
        })

        queries.append({
            "category": category,
            "strategy": "portfolio-traction",
            "query": (
                f'"{name}" portfolio '
                f'"{geography}" "{stage}" startup'
            ),
        })

    # One transaction-oriented query helps discover entities
    # that do not appear in generic investor directories.
    queries.extend([
        {
            "category": "VC",
            "strategy": "transaction",
            "query": (
                f'"{geography}" startup "{stage}" '
                f'"investment round" "venture capital"'
            ),
        },
        {
            "category": "ANGEL",
            "strategy": "transaction",
            "query": (
                f'"{geography}" startup "{stage}" '
                f'"angel investor" funding'
            ),
        },
    ])

    seen = set()
    output = []

    for item in queries:
        key = normalize_text(
            item["query"]
        )

        if key in seen:
            continue

        seen.add(key)
        output.append(item)

    return output


# ============================================================
# SCORING
# ============================================================

def calculate_final_score(
    candidate: Dict[str, Any],
) -> float:
    discovery = candidate.get(
        "discovery_score",
        0,
    )

    evidence = candidate.get(
        "evidence_score",
        0,
    )

    diversity = candidate.get(
        "source_diversity",
        0,
    )

    source_quality_value = candidate.get(
        "average_source_quality",
        0,
    )

    discovery_count = min(
        1.0,
        candidate.get(
            "discovery_count",
            0,
        ) / 4,
    )

    # Evidence dominates discovery.
    score = (
        discovery * 0.15
        + evidence * 0.60
        + diversity * 0.10
        + source_quality_value * 0.05
        + discovery_count * 0.10
    )

    if candidate.get(
        "verification_status"
    ) == "STRONGLY_VERIFIED":
        score += 0.05

    if candidate.get(
        "verification_status"
    ) == "WEAK":
        score -= 0.15

    return round(
        max(
            0.0,
            min(
                score,
                0.99,
            ),
        ),
        3,
    )


def build_entity(
    candidate: Dict[str, Any],
    user_query: str,
) -> Optional[Dict[str, Any]]:
    name = candidate.get("name", "")

    if not is_valid_organization(name):
        return None

    final_score = calculate_final_score(
        candidate
    )

    # Weak candidates never become graph entities.
    if final_score < 0.35:
        return None

    category = (
        candidate.get("categories") or ["INVESTOR"]
    )[0]

    signals = candidate.get(
        "evidence_signals",
        {},
    )

    stage = (
        detect_stage(user_query)
        if signals.get("stage")
        else "Unknown"
    )

    evidence = candidate.get(
        "evidence",
        [],
    )

    best_evidence = sorted(
        evidence,
        key=lambda x: x.get(
            "quality",
            0,
        ),
        reverse=True,
    )[:3]

    relationship = candidate.get(
        "relationship",
        "INVESTOR_TO_STARTUP",
    )

    confidence = final_score

    if candidate.get(
        "verification_status"
    ) == "STRONGLY_VERIFIED":
        confidence = min(
            0.99,
            confidence + 0.05,
        )

    return {
        "id": str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                normalize_name(name),
            )
        ),
        "name": name,
        "normalized_name": normalize_name(name),
        "type": category,
        "country": detect_geography(user_query),
        "stage": stage,
        "relationship": relationship,
        "confidence": round(
            confidence,
            3,
        ),
        "traction": {
            "discovery_count": candidate.get(
                "discovery_count",
                0,
            ),
            "discovery_score": candidate.get(
                "discovery_score",
                0,
            ),
            "source_count": candidate.get(
                "source_count",
                0,
            ),
            "source_diversity": candidate.get(
                "source_diversity",
                0,
            ),
            "domain_count": candidate.get(
                "domain_count",
                0,
            ),
        },
        "evidence": best_evidence,
        "evidence_signals": signals,
        "verification_status": candidate.get(
            "verification_status",
            "UNKNOWN",
        ),
        "verification_score": candidate.get(
            "verification_score",
            0,
        ),
        "final_score": final_score,
        "providers": [
            "exa",
            "tavily",
        ],
        "source": "Exa + Tavily",
        "search_query": user_query,
    }


# ============================================================
# STOPPING CONDITIONS
# ============================================================

def should_stop(
    verified: List[Dict[str, Any]],
    requested_limit: int,
    budget: RequestBudget,
) -> bool:
    entities = [
        item
        for item in verified
        if calculate_final_score(item) >= 0.50
    ]

    strong = [
        item
        for item in verified
        if item.get(
            "verification_status"
        ) == "STRONGLY_VERIFIED"
    ]

    # Stop early when we have enough high-quality results.
    target = min(
        requested_limit,
        10,
    )

    if len(entities) >= target:
        return True

    # Also stop if provider budget is effectively exhausted.
    if (
        budget.remaining["tavily"] <= 2
        and budget.remaining["exa"] <= 1
    ):
        return True

    # If we have several strong entities, another search round
    # often adds duplicates rather than useful new nodes.
    if len(strong) >= min(requested_limit, 8):
        return True

    return False


# ============================================================
# RESEARCH PIPELINE
# ============================================================

async def search_web(
    query: str,
    adaptive: bool = True,
    limit: int = 25,
    budget_tier: str = "balanced",
) -> Dict[str, Any]:
    query = query.strip()

    budget = RequestBudget(
        budget_tier
    )

    print()
    print("=" * 70)
    print(f"🔎 Connecting the Dots: {query}")
    print("=" * 70)

    categories = detect_categories(query)
    stage = detect_stage(query)
    geography = detect_geography(query)

    print(f"🌍 Geography: {geography}")
    print(f"🎯 Stage: {stage}")
    print(f"🏷 Categories: {categories}")

    # --------------------------------------------------------
    # PHASE 0: Query-level cache
    # --------------------------------------------------------

    query_cache_key = hash_key(
        query,
        limit,
        budget_tier,
        adaptive,
    )

    cached_result = await cache_get(
        "research",
        query_cache_key,
    )

    if cached_result is not None:
        cached_result["metadata"]["cache_hit"] = True
        return cached_result

    # --------------------------------------------------------
    # PHASE 1: Discovery
    # --------------------------------------------------------

    discovery_queries = build_discovery_queries(
        query,
        budget_tier=budget_tier,
    )

    print(
        f"🧠 Discovery queries: "
        f"{len(discovery_queries)}"
    )

    semaphore = asyncio.Semaphore(
        MAX_CONCURRENT_SEARCHES
    )

    async def limited_exa(
        item: Dict[str, str],
        adaptive_call: bool = False,
    ) -> List[Dict[str, Any]]:
        async with semaphore:
            return await exa_search(
                item,
                budget,
                adaptive=adaptive_call,
            )

    responses = await asyncio.gather(
        *[
            limited_exa(item)
            for item in discovery_queries
        ],
        return_exceptions=True,
    )

    raw_results: List[Dict[str, Any]] = []

    for response in responses:
        if isinstance(response, Exception):
            print(
                f"⚠️ Discovery failed: {response}"
            )
            continue

        raw_results.extend(response)

    print(
        f"🟣 Raw Exa results: "
        f"{len(raw_results)}"
    )

    # --------------------------------------------------------
    # PHASE 2: Entity resolution + cheap ranking
    # --------------------------------------------------------

    candidates = merge_candidates(
        raw_results
    )

    print(
        f"🎯 Candidate organizations: "
        f"{len(candidates)}"
    )

    # --------------------------------------------------------
    # PHASE 3: Expensive verification only for top candidates
    # --------------------------------------------------------

    tier_limits = {
        "cheap": (2, 4),
        "balanced": (MAX_DEEP_VERIFY, MAX_LIGHT_VERIFY),
        "deep": (MAX_DEEP_VERIFY, MAX_LIGHT_VERIFY),
    }
    deep_limit, light_limit = tier_limits.get(
        budget_tier,
        tier_limits["balanced"],
    )

    deep_candidates = candidates[
        :deep_limit
    ]

    light_candidates = candidates[
        deep_limit:
        deep_limit + light_limit
    ]

    verified: List[Dict[str, Any]] = []

    async def verify(
        candidate: Dict[str, Any],
        depth: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            return await verify_candidate(
                candidate,
                query,
                budget,
                depth=depth,
            )
        except Exception as exc:
            print(
                f"⚠️ Verification failed for "
                f"{candidate.get('name')}: {exc}"
            )
            return None

    # Deep verification for the highest-value candidates.
    deep_results = await asyncio.gather(
        *[
            verify(candidate, "deep")
            for candidate in deep_candidates
        ],
        return_exceptions=True,
    )

    for result in deep_results:
        if (
            isinstance(result, dict)
            and result.get("name")
        ):
            verified.append(result)

    # Light verification for the next tier.
    if not should_stop(
        verified,
        limit,
        budget,
    ):
        light_results = await asyncio.gather(
            *[
                verify(candidate, "light")
                for candidate in light_candidates
            ],
            return_exceptions=True,
        )

        for result in light_results:
            if (
                isinstance(result, dict)
                and result.get("name")
            ):
                verified.append(result)

    # --------------------------------------------------------
    # PHASE 4: Adaptive discovery
    # --------------------------------------------------------

    adaptive_queries: List[Dict[str, str]] = []
    adaptive_raw: List[Dict[str, Any]] = []

    if (
        adaptive
        and budget.remaining["adaptive_exa"] > 0
        and not should_stop(
            verified,
            limit,
            budget,
        )
    ):
        adaptive_queries = build_adaptive_queries(
            verified,
            query,
        )

        adaptive_responses = await asyncio.gather(
            *[
                limited_exa(
                    item,
                    adaptive_call=True,
                )
                for item in adaptive_queries
            ],
            return_exceptions=True,
        )

        for response in adaptive_responses:
            if isinstance(response, Exception):
                continue

            adaptive_raw.extend(response)

        print(
            f"🔄 Adaptive Exa results: "
            f"{len(adaptive_raw)}"
        )

        adaptive_candidates = merge_candidates(
            adaptive_raw
        )

        existing_names = {
            item["normalized_name"]
            for item in verified
        }

        new_candidates = [
            candidate
            for candidate in adaptive_candidates
            if candidate["normalized_name"]
            not in existing_names
        ][:MAX_ADAPTIVE_VERIFY]

        adaptive_verified = await asyncio.gather(
            *[
                verify(candidate, "light")
                for candidate in new_candidates
            ],
            return_exceptions=True,
        )

        for result in adaptive_verified:
            if (
                isinstance(result, dict)
                and result.get("name")
            ):
                verified.append(result)

    # --------------------------------------------------------
    # PHASE 5: Final entity scoring
    # --------------------------------------------------------

    entities: List[Dict[str, Any]] = []
    seen_names: Set[str] = set()

    for candidate in verified:
        entity = build_entity(
            candidate,
            query,
        )

        if not entity:
            continue

        normalized_name = entity[
            "normalized_name"
        ]

        if normalized_name in seen_names:
            continue

        seen_names.add(normalized_name)
        entities.append(entity)

    entities.sort(
        key=lambda item: (
            item.get("final_score", 0),
            item.get("confidence", 0),
        ),
        reverse=True,
    )

    entities = entities[:min(
        limit,
        25,
    )]

    result = {
        "entities": entities,
        "metadata": {
            "query": query,
            "geography": geography,
            "stage": stage,
            "categories": categories,
            "discovery_queries": len(
                discovery_queries
            ),
            "raw_discovery_results": len(
                raw_results
            ),
            "initial_candidates": len(
                candidates
            ),
            "deep_verified": len(
                deep_candidates
            ),
            "light_verified": len(
                light_candidates
            ),
            "adaptive_queries": len(
                adaptive_queries
            ),
            "adaptive_results": len(
                adaptive_raw
            ),
            "verified_candidates": len(
                verified
            ),
            "final_entities": len(
                entities
            ),
            "adaptive_enabled": adaptive,
            "cache_hit": False,
            "budget": budget.snapshot(),
        },
    }

    await cache_set(
        "research",
        query_cache_key,
        result,
        SEARCH_CACHE_TTL,
    )

    return result


# ============================================================
# RELATIONSHIP GRAPH
# ============================================================

def build_relationships(
    entities: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    relationships = []

    for entity in entities:
        relationship = entity.get("relationship")

        if not relationship:
            continue

        entity_id = entity.get("id")
        entity_name = entity.get("name")

        if not entity_id or not entity_name:
            continue

        # Determine the conceptual target node.
        if relationship == "LP_TO_FUND":
            target_name = "Venture Capital Fund"
            target_type = "VENTURE_FUND"

        elif relationship == "ACCELERATOR_TO_STARTUP":
            target_name = (
                f"{entity.get('stage', 'Early Stage')} "
                f"Startup"
            )
            target_type = "EARLY_STAGE_STARTUP"

        elif relationship == "INCUBATOR_TO_STARTUP":
            target_name = (
                f"{entity.get('stage', 'Early Stage')} "
                f"Startup"
            )
            target_type = "EARLY_STAGE_STARTUP"

        else:
            target_name = (
                f"{entity.get('stage', 'Early Stage')} "
                f"Startup"
            )

            target_type = (
                "INDIAN_EARLY_STAGE_STARTUP"
                if entity.get("country") == "India"
                else "EARLY_STAGE_STARTUP"
            )

        # Stable ID for the conceptual target node.
        target_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                normalize_name(
                    f"{target_type}:{target_name}"
                ),
            )
        )

        relationships.append({
            "id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{entity_id}:{relationship}:{target_id}",
                )
            ),

            # Graph edge
            "source": entity_id,
            "target": target_id,

            # Human-readable names
            "source_name": entity_name,
            "target_name": target_name,

            # Node types
            "source_type": entity.get(
                "type",
                "UNKNOWN",
            ),
            "target_type": target_type,

            # Relationship
            "relationship": relationship,

            # Context
            "geography": entity.get("country"),
            "stage": entity.get("stage"),

            # Confidence
            "confidence": entity.get(
                "confidence",
                0,
            ),
            "verification_status": entity.get(
                "verification_status",
                "UNKNOWN",
            ),

            # Evidence
            "evidence": entity.get(
                "evidence",
                [],
            )[:2],
        })

    return relationships


# ============================================================
# TRACTION ANALYTICS
# ============================================================

def calculate_traction(
    entities: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not entities:
        return {
            "discovered": 0,
            "verified": 0,
            "strongly_verified": 0,
            "verification_rate": 0,
            "average_confidence": 0,
            "average_source_diversity": 0,
            "category_coverage": {},
        }

    verified = [
        entity
        for entity in entities
        if entity.get(
            "verification_status"
        ) in {
            "VERIFIED",
            "STRONGLY_VERIFIED",
        }
    ]

    strongly_verified = [
        entity
        for entity in entities
        if entity.get(
            "verification_status"
        ) == "STRONGLY_VERIFIED"
    ]

    categories: Dict[str, int] = {}

    for entity in entities:
        category = entity.get(
            "type",
            "UNKNOWN",
        )

        categories[category] = (
            categories.get(category, 0) + 1
        )

    return {
        "discovered": len(entities),
        "verified": len(verified),
        "strongly_verified": len(
            strongly_verified
        ),
        "verification_rate": round(
            len(verified) / len(entities),
            3,
        ),
        "average_confidence": round(
            sum(
                entity.get(
                    "confidence",
                    0,
                )
                for entity in entities
            ) / len(entities),
            3,
        ),
        "average_source_diversity": round(
            sum(
                entity.get(
                    "traction",
                    {},
                ).get(
                    "source_diversity",
                    0,
                )
                for entity in entities
            ) / len(entities),
            3,
        ),
        "category_coverage": categories,
    }


# ============================================================
# RESEARCH RESPONSE
# ============================================================

async def research_query(
    query: str,
    adaptive: bool = True,
    limit: int = 25,
    budget_tier: str = "balanced",
) -> Dict[str, Any]:
    result = await search_web(
        query,
        adaptive=adaptive,
        limit=limit,
        budget_tier=budget_tier,
    )

    entities = result["entities"][
        :min(limit, 25)
    ]

    relationships = build_relationships(
        entities
    )

    traction = calculate_traction(
        entities
    )

    answer_parts = [
        (
            f"Found {len(entities)} organizations "
            f"relevant to \"{query}\"."
        ),
        "",
        "Research evolution:",
        (
            f"- Discovery candidates: "
            f"{result['metadata']['initial_candidates']}"
        ),
        (
            f"- Deep verified: "
            f"{result['metadata']['deep_verified']}"
        ),
        (
            f"- Light verified: "
            f"{result['metadata']['light_verified']}"
        ),
        (
            f"- Adaptive discoveries: "
            f"{result['metadata']['adaptive_results']}"
        ),
        (
            f"- Final organizations: "
            f"{len(entities)}"
        ),
        (
            f"- Verified: "
            f"{traction['verified']}"
        ),
        (
            f"- Strongly verified: "
            f"{traction['strongly_verified']}"
        ),
        (
            f"- Verification rate: "
            f"{traction['verification_rate']}"
        ),
        "",
        "Top organizations:",
    ]

    for entity in entities:
        answer_parts.append(
            (
                f"- {entity['name']} "
                f"({entity['type']}) "
                f"| stage={entity['stage']} "
                f"| confidence={entity['confidence']} "
                f"| {entity['verification_status']}"
            )
        )

    return {
        "answer": "\n".join(answer_parts),
        "entities": entities,
        # Keep the existing API field.
        "relationships": relationships,
        # Frontend-friendly alias.
        "connections": relationships,
        "opportunities": [],
        "investors": entities,
        "citations": [
            evidence
            for entity in entities
            for evidence in entity.get(
                "evidence",
                [],
            )
        ][:50],
        "providers": {
            "exa": True,
            "tavily": True,
        },
        "stats": {
            **result["metadata"],
            **traction,
        },
    }


# ============================================================
# API
# ============================================================

@app.post("/api/research")
async def perform_research(
    request: ResearchRequest,
):
    query = request.query.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Query cannot be empty.",
        )

    try:
        results = await research_query(
            query,
            adaptive=request.adaptive,
            limit=request.limit,
            budget_tier=request.budget_tier,
        )

        return {
            "research_run_id": str(
                uuid.uuid4()
            ),
            "status": "completed",
            "results": {
                "query": query,
                "response": results,
                "sources": results.get(
                    "citations",
                    [],
                ),
            },
        }

    except Exception as exc:
        print(
            f"❌ Research error: {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Research pipeline failed. "
                "Check backend logs for details."
            ),
        )


# ============================================================
# ENTITY SEARCH
# ============================================================

@app.get("/api/entities/search")
async def search_entities(
    query: str,
    limit: int = 10,
    budget_tier: str = "cheap",
):
    query = (query or "").strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Query cannot be empty.",
        )

    limit = max(
        1,
        min(
            limit,
            MAX_CANDIDATES,
        ),
    )

    result = await search_web(
        query,
        adaptive=False,
        limit=limit,
        budget_tier=budget_tier,
    )

    entities = result["entities"][:limit]

    return {
        "query": query,
        "entities": entities,
        "count": len(entities),
        "providers": {
            "exa": True,
            "tavily": True,
        },
        "traction": calculate_traction(
            entities
        ),
        "stats": result["metadata"],
    }


# ============================================================
# CACHE
# ============================================================

@app.delete("/api/cache")
async def clear_cache():
    async with _cache_lock:
        try:
            with sqlite3.connect(CACHE_PATH) as conn:
                conn.execute("DELETE FROM cache")
                conn.commit()

            return {
                "status": "cleared"
            }

        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not clear cache: {exc}",
            )


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
async def health_check():
    await cache_cleanup()

    return {
        "status": "healthy",
        "mode": "exa+tavily+budgeted-cache-adaptive",
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "providers": {
            "exa": {
                "configured": bool(EXA_API_KEY),
                "role": "semantic entity discovery",
            },
            "tavily": {
                "configured": bool(TAVILY_API_KEY),
                "role": "targeted evidence verification",
            },
        },
        "limits": {
            "max_candidates": MAX_CANDIDATES,
            "max_deep_verify": MAX_DEEP_VERIFY,
            "max_light_verify": MAX_LIGHT_VERIFY,
            "max_adaptive_verify": MAX_ADAPTIVE_VERIFY,
            "tavily_results_per_query": MAX_TAVILY_RESULTS,
        },
        "cache": {
            "path": CACHE_PATH,
            "search_ttl_seconds": SEARCH_CACHE_TTL,
            "profile_ttl_seconds": PROFILE_CACHE_TTL,
            "evidence_ttl_seconds": EVIDENCE_CACHE_TTL,
        },
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():
    return {
        "message": "Connecting the Dots AI",
        "version": "4.0.0",
        "docs": "/docs",
        "health": "/api/health",
        "pipeline": (
            "query understanding -> "
            "cached Exa discovery -> "
            "URL/entity deduplication -> "
            "cheap candidate ranking -> "
            "targeted Tavily verification -> "
            "adaptive discovery when necessary -> "
            "confidence scoring -> "
            "relationship graph"
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
        port=8000,
    )
