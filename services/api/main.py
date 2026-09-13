import os
import re
import uuid
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Set
from urllib.parse import urlparse

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
    version="3.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://connecting-the-dots-web.vercel.app",
    ],
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

tavily_client = TavilyClient(
    api_key=TAVILY_API_KEY
)

exa_client = Exa(
    api_key=EXA_API_KEY
)


# ============================================================
# REQUEST MODELS
# ============================================================

class ResearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = "anonymous"

    # Number of final organizations desired.
    limit: int = Field(default=25, ge=1, le=25)

    # Enables adaptive second-pass research.
    adaptive: bool = True


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


DIRECT_STARTUP_INVESTORS = {
    "VC",
    "ANGEL",
    "ACCELERATOR",
    "INCUBATOR",
    "FAMILY_OFFICE",
    "FOUNDATION",
}


# Exa is discovery.
EXA_MAX_RESULTS = 8

# More candidates are retained before verification.
MAX_CANDIDATES = 40
MAX_FINAL_RESULTS = 25

# Tavily verification.
MAX_TAVILY_RESULTS = 5

# Don't explode API usage.
MAX_CONCURRENT_SEARCHES = 8

# Adaptive second pass.
MAX_ADAPTIVE_QUERIES = 10


# ============================================================
# GENERIC NAME FILTERS
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
}


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    value = str(value)

    value = value.lower()

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_name(value: str) -> str:
    value = normalize_text(value)

    value = re.sub(
        r"[^a-z0-9\s&]",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_url(url: str) -> str:
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        return (
            parsed.netloc
            .lower()
            .replace("www.", "")
        )

    except Exception:
        return ""


def domain_from_url(url: str) -> str:
    return normalize_url(url)


# ============================================================
# ORGANIZATION NAME VALIDATION
# ============================================================

def clean_organization_name(
    name: str,
) -> str:

    if not name:
        return ""

    name = name.strip()

    name = re.sub(
        r"^[\s\-–—|:;,]+",
        "",
        name,
    )

    name = re.sub(
        r"[\s\-–—|:;,]+$",
        "",
        name,
    )

    name = re.sub(
        r"\s+(is|are|was|were|has|have|provides|offers|invests).*$",
        "",
        name,
        flags=re.IGNORECASE,
    )

    name = re.sub(
        r"\s+",
        " ",
        name,
    )

    return name.strip()


def looks_generic(
    name: str,
) -> bool:

    normalized = normalize_name(name)

    if not normalized:
        return True

    if normalized in GENERIC_NAMES:
        return True

    patterns = [
        r"^top\s+",
        r"^best\s+",
        r"^list\s+of\s+",
        r"^ranking",
        r"^guide",
        r"^directory",
        r"^how\s+to",
        r"^where\s+to",
        r"^who\s+",
        r"^investors?\s+in\s+",
        r"^venture\s+capital\s+firms?",
        r"^venture\s+capital\s+investors?",
        r"^venture\s+capital\s+funds?",
        r"^seed\s+investors?",
        r"^seed\s+funds?",
        r"^angel\s+investors?",
        r"^startup\s+investors?",
        r"\bin\s+india$",
        r"\bfor\s+startups$",
    ]

    return any(
        re.search(
            pattern,
            normalized,
        )
        for pattern in patterns
    )


def is_valid_organization(
    name: str,
) -> bool:

    name = clean_organization_name(name)

    if not name:
        return False

    if looks_generic(name):
        return False

    if len(name) < 2:
        return False

    if len(name) > 100:
        return False

    words = name.split()

    if len(words) > 10:
        return False

    return True


# ============================================================
# ARTICLE DETECTION
# ============================================================

def is_listicle(
    title: str,
) -> bool:

    title = normalize_text(title)

    if not title:
        return True

    patterns = [
        "top ",
        "best ",
        "list of",
        "ranking",
        "rankings",
        "directory",
        "guide",
        "complete guide",
        "ultimate guide",
        "investors in india",
        "venture capital firms",
        "startup investors",
        "angel investors",
        "funds investing",
        "firms investing",
        "2023",
        "2024",
        "2025",
        "2026",
    ]

    return any(
        pattern in title
        for pattern in patterns
    )


# ============================================================
# QUERY UNDERSTANDING
# ============================================================

def detect_geography(
    query: str,
) -> str:

    q = normalize_text(query)

    if (
        "india" in q
        or "indian" in q
    ):
        return "India"

    if (
        "uae" in q
        or "united arab emirates" in q
    ):
        return "UAE"

    return "India"


def detect_stage(
    query: str,
) -> str:

    q = normalize_text(query)

    if (
        "pre-seed" in q
        or "pre seed" in q
    ):
        return "pre-seed"

    if "seed" in q:
        return "seed"

    if (
        "early stage" in q
        or "early-stage" in q
    ):
        return "early stage"

    return "early stage"


def detect_categories(
    query: str,
) -> List[str]:

    q = normalize_text(query)

    aliases = {
        "VC": [
            "vc",
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

    categories = []

    padded = f" {q} "

    for category, terms in aliases.items():

        if any(
            term in padded
            for term in terms
        ):
            categories.append(category)

    if not categories:
        return CATEGORIES.copy()

    return categories


# ============================================================
# DISCOVERY STRATEGIES
# ============================================================

def build_discovery_queries(
    user_query: str,
) -> List[Dict[str, str]]:

    geography = detect_geography(
        user_query
    )

    stage = detect_stage(
        user_query
    )

    categories = detect_categories(
        user_query
    )

    queries = []

    for category in categories:

        if category == "VC":

            queries.extend([
                {
                    "category": "VC",
                    "strategy": "direct",
                    "query": (
                        f'"{geography}" '
                        f'"venture capital" '
                        f'"{stage}" startups'
                    ),
                },
                {
                    "category": "VC",
                    "strategy": "portfolio",
                    "query": (
                        f'"{geography}" VC '
                        f'portfolio startups '
                        f'"{stage}"'
                    ),
                },
                {
                    "category": "VC",
                    "strategy": "thesis",
                    "query": (
                        f'"India" '
                        f'"investment thesis" '
                        f'"{stage}" '
                        f'"venture capital"'
                    ),
                },
            ])

        elif category == "ANGEL":

            queries.extend([
                {
                    "category": "ANGEL",
                    "strategy": "direct",
                    "query": (
                        f'India angel investor '
                        f'"{stage}" startups'
                    ),
                },
                {
                    "category": "ANGEL",
                    "strategy": "portfolio",
                    "query": (
                        f'India angel network '
                        f'portfolio startup investment'
                    ),
                },
            ])

        elif category == "ACCELERATOR":

            queries.extend([
                {
                    "category": "ACCELERATOR",
                    "strategy": "program",
                    "query": (
                        f'India startup accelerator '
                        f'investment "{stage}"'
                    ),
                },
                {
                    "category": "ACCELERATOR",
                    "strategy": "portfolio",
                    "query": (
                        f'India accelerator '
                        f'portfolio companies startup investment'
                    ),
                },
            ])

        elif category == "INCUBATOR":

            queries.extend([
                {
                    "category": "INCUBATOR",
                    "strategy": "program",
                    "query": (
                        f'India startup incubator '
                        f'investment "{stage}"'
                    ),
                },
                {
                    "category": "INCUBATOR",
                    "strategy": "portfolio",
                    "query": (
                        f'India incubator '
                        f'portfolio startups funding'
                    ),
                },
            ])

        elif category == "FAMILY_OFFICE":

            queries.extend([
                {
                    "category": "FAMILY_OFFICE",
                    "strategy": "direct",
                    "query": (
                        f'India family office '
                        f'startup investment "{stage}"'
                    ),
                },
                {
                    "category": "FAMILY_OFFICE",
                    "strategy": "portfolio",
                    "query": (
                        f'Indian family office '
                        f'venture portfolio startups'
                    ),
                },
            ])

        elif category == "FOUNDATION":

            queries.extend([
                {
                    "category": "FOUNDATION",
                    "strategy": "impact",
                    "query": (
                        f'India foundation '
                        f'impact startup investment'
                    ),
                },
                {
                    "category": "FOUNDATION",
                    "strategy": "portfolio",
                    "query": (
                        f'India foundation '
                        f'social enterprise startup portfolio'
                    ),
                },
            ])

        elif category == "LP":

            queries.extend([
                {
                    "category": "LP",
                    "strategy": "fund",
                    "query": (
                        f'India limited partner '
                        f'venture capital fund'
                    ),
                },
                {
                    "category": "LP",
                    "strategy": "institutional",
                    "query": (
                        f'India institutional investor '
                        f'venture capital funds'
                    ),
                },
                {
                    "category": "LP",
                    "strategy": "fund-of-funds",
                    "query": (
                        f'India fund of funds '
                        f'venture capital startup ecosystem'
                    ),
                },
            ])

    # Deduplicate.
    seen = set()
    unique = []

    for item in queries:

        key = normalize_text(
            item["query"]
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

    return unique


# ============================================================
# EXA
# ============================================================

async def exa_search(
    item: Dict[str, str],
) -> List[Dict[str, Any]]:

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
                    "max_characters": 7000
                }
            },
        )

        output = []

        for result in getattr(
            response,
            "results",
            [],
        ):

            url = getattr(
                result,
                "url",
                "",
            ) or ""

            if not url:
                continue

            output.append({
                "title": getattr(
                    result,
                    "title",
                    "",
                ) or "",

                "content": getattr(
                    result,
                    "text",
                    "",
                ) or "",

                "url": url,

                "author": getattr(
                    result,
                    "author",
                    "",
                ) or "",

                "published_date": getattr(
                    result,
                    "published_date",
                    "",
                ) or "",

                "provider": "exa",

                "category": item[
                    "category"
                ],

                "strategy": item[
                    "strategy"
                ],

                "search_query": query,

                "score": 0.0,
            })

        return output

    except Exception as exc:

        print(
            f"⚠️ Exa failed: {exc}"
        )

        return []


# ============================================================
# TAVILY
# ============================================================

async def tavily_search(
    query: str,
    category: str,
    purpose: str,
) -> List[Dict[str, Any]]:

    print(
        f"🔵 Tavily [{category}/{purpose}]: "
        f"{query}"
    )

    try:

        response = await asyncio.to_thread(
            tavily_client.search,
            query=query,
            search_depth="advanced",
            max_results=MAX_TAVILY_RESULTS,
            include_answer=False,
            include_raw_content=True,
        )

        results = []

        for item in response.get(
            "results",
            [],
        ):

            url = item.get(
                "url",
                "",
            ) or ""

            if not url:
                continue

            results.append({
                "title": item.get(
                    "title",
                    "",
                ) or "",

                "content": item.get(
                    "content",
                    "",
                ) or "",

                "raw_content": item.get(
                    "raw_content",
                    "",
                ) or "",

                "url": url,

                "score": item.get(
                    "score",
                    0,
                ) or 0,

                "provider": "tavily",

                "category": category,

                "purpose": purpose,

                "search_query": query,
            })

        return results

    except Exception as exc:

        print(
            f"⚠️ Tavily failed: {exc}"
        )

        return []


# ============================================================
# DOMAIN / ORGANIZATION EXTRACTION
# ============================================================

def domain_brand(
    url: str,
) -> str:

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
    }:
        return ""

    return (
        first
        .replace("-", " ")
        .replace("_", " ")
        .title()
    )


def extract_organization(
    result: Dict[str, Any],
) -> Optional[str]:

    title = result.get(
        "title",
        "",
    )

    content = result.get(
        "content",
        "",
    )

    raw = result.get(
        "raw_content",
        "",
    )

    url = result.get(
        "url",
        "",
    )

    combined = (
        f"{title}\n"
        f"{content}\n"
        f"{raw[:10000]}"
    )

    # --------------------------------------------------------
    # Explicit organization statements.
    # --------------------------------------------------------

    patterns = [
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)"
        r"\s+(?:is|are)\s+(?:a|an|the)\s+"
        r"(?:venture capital|venture|investment|"
        r"angel|startup|accelerator|incubator|"
        r"family office|foundation)",

        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)"
        r"\s+(?:invests|invested|investing)"
        r"\s+(?:in|into)\b",

        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)"
        r"\s+(?:backs|backed|backing)\b",

        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,70}?)"
        r"\s+(?:portfolio|portfolio companies)\b",
    ]

    for pattern in patterns:

        try:

            matches = re.findall(
                pattern,
                combined,
                flags=re.IGNORECASE,
            )

        except Exception:
            continue

        for match in matches:

            candidate = (
                match
                if isinstance(
                    match,
                    str,
                )
                else match[0]
            )

            candidate = clean_organization_name(
                candidate
            )

            if is_valid_organization(
                candidate
            ):
                return candidate

    # --------------------------------------------------------
    # Title fallback.
    # --------------------------------------------------------

    if (
        title
        and not is_listicle(title)
    ):

        candidate = clean_organization_name(
            title
        )

        if is_valid_organization(
            candidate
        ):
            return candidate

    # --------------------------------------------------------
    # Domain fallback.
    # --------------------------------------------------------

    text = normalize_text(
        combined
    )

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

        candidate = domain_brand(
            url
        )

        if is_valid_organization(
            candidate
        ):
            return candidate

    return None


# ============================================================
# CANDIDATE MERGING
# ============================================================

def merge_candidates(
    results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    candidates = {}

    for result in results:

        organization = extract_organization(
            result
        )

        if not organization:
            continue

        normalized = normalize_name(
            organization
        )

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
            }

        candidate = candidates[
            normalized
        ]

        candidate["results"].append(
            result
        )

        candidate["categories"].add(
            result.get(
                "category",
                "UNKNOWN",
            )
        )

        candidate["strategies"].add(
            result.get(
                "strategy",
                "unknown",
            )
        )

        domain = domain_from_url(
            result.get(
                "url",
                "",
            )
        )

        if domain:
            candidate["domains"].add(
                domain
            )

        candidate[
            "discovery_count"
        ] += 1

    output = []

    for candidate in candidates.values():

        candidate["categories"] = list(
            candidate["categories"]
        )

        candidate["strategies"] = list(
            candidate["strategies"]
        )

        candidate["domains"] = list(
            candidate["domains"]
        )

        # Discovery traction.
        candidate[
            "discovery_score"
        ] = min(
            1.0,
            (
                candidate[
                    "discovery_count"
                ] * 0.15
            )
            + (
                len(
                    candidate[
                        "strategies"
                    ]
                ) * 0.10
            )
            + (
                len(
                    candidate[
                        "categories"
                    ]
                ) * 0.05
            ),
        )

        output.append(
            candidate
        )

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
) -> List[Tuple[str, str]]:

    name = candidate["name"]

    category = (
        candidate[
            "categories"
        ][0]
        if candidate.get(
            "categories"
        )
        else "VC"
    )

    stage = detect_stage(
        user_query
    )

    queries = [
        (
            f'"{name}" India '
            f'"{stage}" startups investment',
            "investment",
        ),

        (
            f'"{name}" India '
            f'portfolio startups',
            "portfolio",
        ),

        (
            f'"{name}" '
            f'investment thesis India',
            "thesis",
        ),

        (
            f'"{name}" '
            f'invested in Indian startup',
            "transaction",
        ),
    ]

    # LPs require a different relationship.
    if category == "LP":

        queries = [
            (
                f'"{name}" '
                f'limited partner venture capital fund',
                "lp_relationship",
            ),
            (
                f'"{name}" '
                f'committed to venture capital fund',
                "fund_commitment",
            ),
            (
                f'"{name}" '
                f'investments in venture funds India',
                "fund_relationship",
            ),
        ]

    return queries


# ============================================================
# EVIDENCE ANALYSIS
# ============================================================

def evidence_signals(
    text: str,
    category: str,
) -> Dict[str, float]:

    text = normalize_text(
        text
    )

    signals = {
        "investment": 0.0,
        "india": 0.0,
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

    if any(
        term in text
        for term in [
            "india",
            "indian startup",
            "indian startups",
        ]
    ):
        signals["india"] = 1.0

    if any(
        term in text
        for term in [
            "pre-seed",
            "pre seed",
            "seed stage",
            "early stage",
            "early-stage",
        ]
    ):
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

    category_terms = {
        "VC": [
            "venture capital",
            "venture fund",
            "venture investor",
        ],

        "ANGEL": [
            "angel investor",
            "angel network",
            "angel fund",
        ],

        "ACCELERATOR": [
            "accelerator",
        ],

        "INCUBATOR": [
            "incubator",
        ],

        "FAMILY_OFFICE": [
            "family office",
        ],

        "FOUNDATION": [
            "foundation",
            "impact investor",
        ],

        "LP": [
            "limited partner",
            "fund of funds",
            "institutional investor",
        ],
    }

    if any(
        term in text
        for term in category_terms.get(
            category,
            [],
        )
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


# ============================================================
# SOURCE QUALITY
# ============================================================

def source_quality(
    result: Dict[str, Any],
) -> float:

    url = result.get(
        "url",
        "",
    )

    title = normalize_text(
        result.get(
            "title",
            "",
        )
    )

    content = normalize_text(
        result.get(
            "content",
            "",
        )
    )

    domain = domain_from_url(
        url
    )

    score = 0.0

    # Official company domain.
    if domain and not any(
        bad in domain
        for bad in [
            "linkedin.com",
            "medium.com",
            "reddit.com",
        ]
    ):
        score += 0.25

    # Direct organization evidence.
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
        score += 0.20

    if not is_listicle(title):
        score += 0.10

    if result.get(
        "provider"
    ) == "tavily":
        score += 0.05

    return min(
        score,
        1.0,
    )


# ============================================================
# VERIFY CANDIDATE
# ============================================================

async def verify_candidate(
    candidate: Dict[str, Any],
    user_query: str,
) -> Dict[str, Any]:

    queries = build_evidence_queries(
        candidate,
        user_query,
    )

    # Limit concurrency.
    semaphore = asyncio.Semaphore(
        MAX_CONCURRENT_SEARCHES
    )

    async def run(query, purpose):

        async with semaphore:

            return await tavily_search(
                query,
                candidate[
                    "categories"
                ][0]
                if candidate.get(
                    "categories"
                )
                else "VC",
                purpose,
            )

    tasks = [
        run(query, purpose)
        for query, purpose in queries
    ]

    responses = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    evidence = []

    for response in responses:

        if isinstance(
            response,
            Exception,
        ):
            continue

        evidence.extend(
            response
        )

    # --------------------------------------------------------
    # Deduplicate sources.
    # --------------------------------------------------------

    unique_sources = {}

    for item in evidence:

        domain = domain_from_url(
            item.get(
                "url",
                "",
            )
        )

        key = (
            item.get(
                "url",
                "",
            )
            or domain
            or item.get(
                "title",
                "",
            )
        )

        if key not in unique_sources:
            unique_sources[key] = item

    evidence = list(
        unique_sources.values()
    )

    # --------------------------------------------------------
    # Analyze evidence.
    # --------------------------------------------------------

    aggregated = {
        "investment": 0.0,
        "india": 0.0,
        "stage": 0.0,
        "portfolio": 0.0,
        "transaction": 0.0,
        "official": 0.0,
        "category": 0.0,
        "contradiction": 0.0,
    }

    source_scores = []
    domains = set()

    evidence_items = []

    for item in evidence:

        text = normalize_text(
            " ".join([
                item.get(
                    "title",
                    "",
                ),
                item.get(
                    "content",
                    "",
                ),
                item.get(
                    "raw_content",
                    "",
                )[:8000],
            ])
        )

        signals = evidence_signals(
            text,
            candidate[
                "categories"
            ][0]
            if candidate.get(
                "categories"
            )
            else "VC",
        )

        quality = source_quality(
            item
        )

        source_scores.append(
            quality
        )

        domain = domain_from_url(
            item.get(
                "url",
                "",
            )
        )

        if domain:
            domains.add(domain)

        for key in aggregated:

            if signals[key] > 0:
                aggregated[key] = max(
                    aggregated[key],
                    signals[key],
                )

        evidence_items.append({
            "url": item.get(
                "url",
                "",
            ),

            "title": item.get(
                "title",
                "",
            ),

            "content": item.get(
                "content",
                "",
            )[:1200],

            "quality": round(
                quality,
                3,
            ),

            "signals": signals,
        })

    # --------------------------------------------------------
    # Cross-source diversity.
    # --------------------------------------------------------

    diversity_score = min(
        1.0,
        len(domains) / 3,
    )

    # --------------------------------------------------------
    # Evidence score.
    # --------------------------------------------------------

    evidence_score = 0.0

    evidence_score += (
        aggregated["investment"] * 0.22
    )

    evidence_score += (
        aggregated["india"] * 0.16
    )

    evidence_score += (
        aggregated["stage"] * 0.14
    )

    evidence_score += (
        aggregated["portfolio"] * 0.15
    )

    evidence_score += (
        aggregated["transaction"] * 0.10
    )

    evidence_score += (
        aggregated["official"] * 0.10
    )

    evidence_score += (
        aggregated["category"] * 0.08
    )

    evidence_score += (
        diversity_score * 0.05
    )

    evidence_score -= (
        aggregated["contradiction"] * 0.25
    )

    evidence_score = max(
        0.0,
        min(
            evidence_score,
            1.0,
        ),
    )

    # --------------------------------------------------------
    # Direct relationship.
    # --------------------------------------------------------

    category = (
        candidate[
            "categories"
        ][0]
        if candidate.get(
            "categories"
        )
        else "VC"
    )

    if category == "LP":

        relationship = (
            "LP_TO_FUND"
        )

    elif category == "ACCELERATOR":

        relationship = (
            "ACCELERATOR_TO_STARTUP"
        )

    elif category == "INCUBATOR":

        relationship = (
            "INCUBATOR_TO_STARTUP"
        )

    else:

        relationship = (
            "INVESTOR_TO_STARTUP"
        )

    # --------------------------------------------------------
    # Verification state.
    # --------------------------------------------------------

    if evidence_score >= 0.70:

        status = (
            "STRONGLY_VERIFIED"
        )

    elif evidence_score >= 0.50:

        status = (
            "VERIFIED"
        )

    elif evidence_score >= 0.35:

        status = (
            "SUPPORTED"
        )

    else:

        status = (
            "WEAK"
        )

    return {
        **candidate,

        "evidence": evidence_items,

        "evidence_signals": aggregated,

        "evidence_score": round(
            evidence_score,
            3,
        ),

        "source_diversity": round(
            diversity_score,
            3,
        ),

        "source_count": len(
            evidence
        ),

        "domain_count": len(
            domains
        ),

        "relationship": relationship,

        "verification_status": status,

        "verification_score": round(
            evidence_score,
            3,
        ),
    }


# ============================================================
# ADAPTIVE QUERY GENERATION
# ============================================================

def build_adaptive_queries(
    candidates: List[Dict[str, Any]],
    user_query: str,
) -> List[Dict[str, str]]:

    geography = detect_geography(
        user_query
    )

    stage = detect_stage(
        user_query
    )

    queries = []

    # --------------------------------------------------------
    # Learn from high-traction organizations.
    # --------------------------------------------------------

    strong = sorted(
        candidates,
        key=lambda x: (
            x.get(
                "evidence_score",
                0,
            ),
            x.get(
                "discovery_score",
                0,
            ),
        ),
        reverse=True,
    )[:10]

    for candidate in strong:

        name = candidate[
            "name"
        ]

        queries.extend([
            {
                "category": candidate[
                    "categories"
                ][0]
                if candidate.get(
                    "categories"
                )
                else "VC",

                "strategy": "traction",

                "query": (
                    f'"{name}" '
                    f'portfolio Indian startups '
                    f'"{stage}"'
                ),
            },

            {
                "category": candidate[
                    "categories"
                ][0]
                if candidate.get(
                    "categories"
                )
                else "VC",

                "strategy": "similar-investors",

                "query": (
                    f'"{name}" '
                    f'co-investors India startup'
                ),
            },
        ])

    # --------------------------------------------------------
    # Find actual investment transactions.
    # --------------------------------------------------------

    queries.extend([
        {
            "category": "VC",
            "strategy": "transaction",
            "query": (
                f'Indian startup "{stage}" '
                f'"investment round" '
                f'"venture capital"'
            ),
        },

        {
            "category": "ANGEL",
            "strategy": "transaction",
            "query": (
                f'Indian startup "{stage}" '
                f'"angel investor" funding'
            ),
        },

        {
            "category": "ACCELERATOR",
            "strategy": "transaction",
            "query": (
                f'India startup accelerator '
                f'investment portfolio'
            ),
        },
    ])

    # Deduplicate.
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

    return output[
        :MAX_ADAPTIVE_QUERIES
    ]


# ============================================================
# FINAL RANKING
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

    discovery_count = min(
        1.0,
        candidate.get(
            "discovery_count",
            0,
        ) / 5,
    )

    score = (
        discovery * 0.20
        + evidence * 0.55
        + diversity * 0.10
        + discovery_count * 0.15
    )

    return round(
        min(
            score,
            0.99,
        ),
        3,
    )


# ============================================================
# BUILD ENTITY
# ============================================================

def build_entity(
    candidate: Dict[str, Any],
    user_query: str,
) -> Optional[Dict[str, Any]]:

    name = candidate.get(
        "name",
        "",
    )

    if not is_valid_organization(
        name
    ):
        return None

    category = (
        candidate[
            "categories"
        ][0]
        if candidate.get(
            "categories"
        )
        else "INVESTOR"
    )

    signals = candidate.get(
        "evidence_signals",
        {},
    )

    final_score = (
        calculate_final_score(
            candidate
        )
    )

    # --------------------------------------------------------
    # Don't promote weak evidence.
    # --------------------------------------------------------

    if final_score < 0.35:
        return None

    # --------------------------------------------------------
    # Stage.
    # --------------------------------------------------------

    stage = "Unknown"

    if signals.get(
        "stage",
        0,
    ):

        stage = detect_stage(
            user_query
        )

    # --------------------------------------------------------
    # Evidence.
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Relationships.
    # --------------------------------------------------------

    relationship = candidate.get(
        "relationship",
        "INVESTOR_TO_STARTUP",
    )

    # --------------------------------------------------------
    # Confidence.
    # --------------------------------------------------------

    confidence = final_score

    if (
        candidate.get(
            "verification_status"
        )
        == "STRONGLY_VERIFIED"
    ):
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

        "normalized_name": normalize_name(
            name
        ),

        "type": category,

        "country": detect_geography(
            user_query
        ),

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

        "source": (
            "Exa + Tavily"
        ),

        "search_query": user_query,
    }


# ============================================================
# RESEARCH PIPELINE
# ============================================================

async def search_web(
    query: str,
    adaptive: bool = True,
) -> Dict[str, Any]:

    print()
    print("=" * 70)
    print(
        f"🔎 Connecting the Dots: {query}"
    )
    print("=" * 70)

    # ========================================================
    # PHASE 1
    # Understand query.
    # ========================================================

    categories = detect_categories(
        query
    )

    stage = detect_stage(
        query
    )

    geography = detect_geography(
        query
    )

    print(
        f"🌍 Geography: {geography}"
    )

    print(
        f"🎯 Stage: {stage}"
    )

    print(
        f"🏷 Categories: {categories}"
    )

    # ========================================================
    # PHASE 2
    # Broad Exa discovery.
    # ========================================================

    discovery_queries = (
        build_discovery_queries(
            query
        )
    )

    print(
        f"🧠 Discovery queries: "
        f"{len(discovery_queries)}"
    )

    semaphore = asyncio.Semaphore(
        MAX_CONCURRENT_SEARCHES
    )

    async def limited_exa(item):

        async with semaphore:
            return await exa_search(
                item
            )

    responses = await asyncio.gather(
        *[
            limited_exa(item)
            for item in discovery_queries
        ],
        return_exceptions=True,
    )

    raw_results = []

    for response in responses:

        if isinstance(
            response,
            Exception,
        ):
            continue

        raw_results.extend(
            response
        )

    print(
        f"🟣 Raw Exa results: "
        f"{len(raw_results)}"
    )

    # ========================================================
    # PHASE 3
    # Entity resolution.
    # ========================================================

    candidates = merge_candidates(
        raw_results
    )

    print(
        f"🎯 Initial entities: "
        f"{len(candidates)}"
    )

    # ========================================================
    # PHASE 4
    # Evidence verification.
    # ========================================================

    verification_tasks = [
        verify_candidate(
            candidate,
            query,
        )
        for candidate in candidates
    ]

    verified_results = await asyncio.gather(
        *verification_tasks,
        return_exceptions=True,
    )

    verified = []

    for result in verified_results:

        if isinstance(
            result,
            Exception,
        ):
            print(
                f"⚠️ Verification failed: "
                f"{result}"
            )
            continue

        verified.append(
            result
        )

    # ========================================================
    # PHASE 5
    # Adaptive evolution.
    # ========================================================

    if adaptive:

        adaptive_queries = (
            build_adaptive_queries(
                verified,
                query,
            )
        )

        print(
            f"🔄 Adaptive queries: "
            f"{len(adaptive_queries)}"
        )

        adaptive_responses = await asyncio.gather(
            *[
                limited_exa(item)
                for item in adaptive_queries
            ],
            return_exceptions=True,
        )

        adaptive_raw = []

        for response in adaptive_responses:

            if isinstance(
                response,
                Exception,
            ):
                continue

            adaptive_raw.extend(
                response
            )

        print(
            f"🟣 Adaptive Exa results: "
            f"{len(adaptive_raw)}"
        )

        # Add new entities.
        adaptive_candidates = (
            merge_candidates(
                adaptive_raw
            )
        )

        existing_names = {
            candidate[
                "normalized_name"
            ]
            for candidate in verified
        }

        new_candidates = [
            candidate
            for candidate in adaptive_candidates
            if candidate[
                "normalized_name"
            ] not in existing_names
        ]

        print(
            f"🌱 New entities from "
            f"adaptive research: "
            f"{len(new_candidates)}"
        )

        # Verify new candidates.
        new_verified_results = await asyncio.gather(
            *[
                verify_candidate(
                    candidate,
                    query,
                )
                for candidate in new_candidates[
                    :15
                ]
            ],
            return_exceptions=True,
        )

        for result in new_verified_results:

            if isinstance(
                result,
                Exception,
            ):
                continue

            verified.append(
                result
            )

    # ========================================================
    # PHASE 6
    # Final scoring.
    # ========================================================

    entities = []

    seen = set()

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

        if normalized_name in seen:
            continue

        seen.add(
            normalized_name
        )

        entities.append(
            entity
        )

    entities.sort(
        key=lambda item: (
            item.get("final_score", 0),
            item.get("confidence", 0),
        ),
        reverse=True,
    )

    # Never expose more than 25 final organizations
    entities = entities[:MAX_FINAL_RESULTS]

    return {
        "entities": entities,
        "metadata": {
            "query": query,
            "geography": geography,
            "stage": stage,
            "categories": categories,
            "discovery_queries": len(discovery_queries),
            "raw_discovery_results": len(raw_results),
            "initial_candidates": len(candidates),
            "final_entities": len(entities),
            "adaptive_enabled": adaptive,
        },
    }


# ============================================================
# RELATIONSHIP GRAPH
# ============================================================

def build_relationships(
    entities: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    relationships = []

    for entity in entities:

        relationship = entity.get(
            "relationship"
        )

        if not relationship:
            continue

        if relationship == "LP_TO_FUND":

            target_type = "VENTURE_FUND"

        else:

            target_type = "INDIAN_EARLY_STAGE_STARTUP"

        relationships.append({
            "source": entity[
                "name"
            ],

            "source_type": entity[
                "type"
            ],

            "relationship": relationship,

            "target_type": target_type,

            "geography": entity.get(
                "country"
            ),

            "stage": entity.get(
                "stage"
            ),

            "confidence": entity.get(
                "confidence"
            ),

            "verification_status": entity.get(
                "verification_status"
            ),
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
            "average_confidence": 0,
            "average_source_diversity": 0,
            "category_coverage": {},
        }

    verified = [
        entity
        for entity in entities
        if entity.get(
            "verification_status"
        )
        in {
            "VERIFIED",
            "STRONGLY_VERIFIED",
        }
    ]

    strongly_verified = [
        entity
        for entity in entities
        if entity.get(
            "verification_status"
        )
        == "STRONGLY_VERIFIED"
    ]

    categories = {}

    for entity in entities:

        category = entity.get(
            "type",
            "UNKNOWN",
        )

        categories[
            category
        ] = (
            categories.get(
                category,
                0,
            )
            + 1
        )

    return {
        "discovered": len(
            entities
        ),

        "verified": len(
            verified
        ),

        "strongly_verified": len(
            strongly_verified
        ),

        "verification_rate": round(
            len(verified)
            / len(entities),
            3,
        ),

        "average_confidence": round(
            sum(
                entity.get(
                    "confidence",
                    0,
                )
                for entity in entities
            )
            / len(entities),
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
            )
            / len(entities),
            3,
        ),

        "category_coverage": categories,
    }


# ============================================================
# RESEARCH
# ============================================================

async def research_query(
    query: str,
    adaptive: bool = True,
    limit: int = 50,
) -> Dict[str, Any]:

    result = await search_web(
        query,
        adaptive=adaptive,
    )

    final_limit = min(limit, MAX_FINAL_RESULTS)
    entities = result["entities"][:final_limit]

    relationships = (
        build_relationships(
            entities
        )
    )

    traction = (
        calculate_traction(
            entities
        )
    )

    # ========================================================
    # Human answer.
    # ========================================================

    answer_parts = [
        (
            f"Found {len(entities)} "
            f"organizations relevant to "
            f'"{query}".'
        ),
        "",
        "Research evolution:",
        (
            f"- Initial discovery: "
            f"{result['metadata']['initial_candidates']} "
            f"candidate organizations"
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

    for entity in entities[:25]:

        answer_parts.append(
            (
                f"- {entity['name']} "
                f"({entity['type']}) "
                f"| stage={entity['stage']} "
                f"| confidence="
                f"{entity['confidence']} "
                f"| "
                f"{entity['verification_status']}"
            )
        )

    return {
        "answer": "\n".join(
            answer_parts
        ),

        "entities": entities,

        "relationships": relationships,

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

@app.post(
    "/api/research"
)
async def perform_research(
    request: ResearchRequest,
):

    query = (
        request.query
        or ""
    ).strip()

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
            detail=str(exc),
        )


# ============================================================
# ENTITY SEARCH
# ============================================================

@app.get(
    "/api/entities/search"
)
async def search_entities(
    query: str,
    limit: int = 10,
):

    query = (
        query
        or ""
    ).strip()

    if not query:

        raise HTTPException(
            status_code=400,
            detail="Query cannot be empty.",
        )

    limit = max(
        1,
        min(
            limit,
            MAX_FINAL_RESULTS,
        ),
    )

    result = await search_web(
        query,
        adaptive=True,
    )

    entities = result[
        "entities"
    ][:limit]

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
    }


# ============================================================
# HEALTH
# ============================================================

@app.get(
    "/api/health"
)
async def health_check():

    return {
        "status": "healthy",
        "mode": "exa+tavily+adaptive",
        "timestamp": datetime.utcnow().isoformat(),

        "providers": {
            "exa": {
                "configured": bool(
                    EXA_API_KEY
                ),
                "role": (
                    "semantic entity discovery"
                ),
            },

            "tavily": {
                "configured": bool(
                    TAVILY_API_KEY
                ),
                "role": (
                    "evidence verification"
                ),
            },
        },
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {
        "message": (
            "Connecting the Dots AI"
        ),

        "version": "3.0.0",

        "docs": "/docs",

        "health": "/api/health",

        "pipeline": (
            "query understanding -> "
            "multi-strategy Exa discovery -> "
            "entity resolution -> "
            "Tavily evidence verification -> "
            "adaptive discovery -> "
            "traction scoring -> "
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