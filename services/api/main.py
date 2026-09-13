import os
import re
import uuid
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from tavily import TavilyClient
from exa_py import Exa


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

app = FastAPI(
    title="Connecting the Dots AI",
    version="2.0.0",
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
    raise RuntimeError(
        "TAVILY_API_KEY is not configured. "
        "Add it to your environment variables."
    )


if not EXA_API_KEY:
    raise RuntimeError(
        "EXA_API_KEY is not configured. "
        "Add it to your environment variables."
    )


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
# MODELS
# ============================================================

class ResearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = "anonymous"


# ============================================================
# INVESTOR CATEGORIES
# ============================================================

INVESTOR_CATEGORIES = {
    "VC": [
        "venture capital",
        "venture capital firm",
        "venture fund",
        "vc fund",
        "startup investor",
    ],

    "ANGEL": [
        "angel investor",
        "angel network",
        "angel investing",
        "angel fund",
    ],

    "ACCELERATOR": [
        "startup accelerator",
        "accelerator",
        "accelerator program",
    ],

    "INCUBATOR": [
        "startup incubator",
        "incubator",
        "incubation",
    ],

    "FAMILY_OFFICE": [
        "family office",
        "family offices",
    ],

    "FOUNDATION": [
        "foundation",
        "impact foundation",
        "philanthropic investor",
    ],

    "LP": [
        "limited partner",
        "limited partners",
        "institutional investor",
        "fund of funds",
    ],
}


# ============================================================
# GENERIC ORGANIZATION NAMES
# ============================================================

GENERIC_ORGANIZATION_NAMES = {
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
    "startup investors in india",
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
# PROVIDER LIMITS
# ============================================================

# Exa is used for broad semantic discovery.
EXA_MAX_RESULTS = 8

# Only verify the strongest candidates with Tavily.
MAX_CANDIDATES_TO_VERIFY = 12

# Tavily searches per candidate.
MAX_TAVILY_VERIFICATION_SEARCHES = 2

# Tavily result count per verification query.
TAVILY_MAX_RESULTS = 5


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    if not isinstance(value, str):
        value = str(value)

    value = value.lower()
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_name(name: str) -> str:
    name = normalize_text(name)

    name = re.sub(
        r"[^a-z0-9\s]",
        "",
        name,
    )

    name = re.sub(
        r"\s+",
        " ",
        name,
    )

    return name.strip()


def normalize_url(url: str) -> str:
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        domain = (
            parsed.netloc
            .lower()
            .replace("www.", "")
        )

        return domain

    except Exception:
        return url.lower().strip()


def clean_organization_name(name: str) -> str:
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
    ).strip()

    return name


# ============================================================
# ARTICLE / LISTICLE DETECTION
# ============================================================

def is_list_or_article(title: str) -> bool:
    title = normalize_text(title)

    if not title:
        return True

    article_patterns = [
        "top ",
        "best ",
        "list of",
        "lists",
        "ranking",
        "rankings",
        "guide",
        "directory",
        "comprehensive list",
        "firms investing",
        "firms in india",
        "investors in india",
        "investors investing",
        "funds in india",
        "funds investing",
        "companies investing",
        "companies in india",
        "who invests",
        "where to find",
        "how to find",
        "review",
        "report",
        "market",
        "comparison",
        "compare",
        "ultimate guide",
        "complete guide",
        "investment guide",
        "startup funding guide",
        "venture capital guide",
        "venture capital firms",
        "venture capital investors",
        "venture capital funds",
        "seed investors",
        "seed funds",
        "angel investors",
        "startup investors",
        "investors investing in",
        "investing in india",
        "funding startups in india",
        "2023",
        "2024",
        "2025",
        "2026",
    ]

    if any(
        pattern in title
        for pattern in article_patterns
    ):
        return True

    if title.endswith("?"):
        return True

    if len(title.split()) > 12:
        return True

    return False


# ============================================================
# ORGANIZATION VALIDATION
# ============================================================

def looks_like_generic_organization(name: str) -> bool:
    normalized = normalize_name(name)

    if not normalized:
        return True

    if normalized in GENERIC_ORGANIZATION_NAMES:
        return True

    generic_patterns = [
        r"^top\s+",
        r"^best\s+",
        r"^list\s+of\s+",
        r"^list\s*:",
        r"^ranking",
        r"^rankings",
        r"^guide\s+to\s+",
        r"^directory",
        r"^how\s+to\s+",
        r"^where\s+to\s+",
        r"^who\s+",
        r"^investors?\s+in\s+",
        r"^venture\s+capital\s+firms?\s+",
        r"^venture\s+capital\s+investors?\s+",
        r"^venture\s+capital\s+funds?\s+",
        r"^seed\s+investors?\s+",
        r"^seed\s+funds?\s+",
        r"^angel\s+investors?\s+",
        r"^startup\s+investors?\s+",
        r"^startup\s+funding",
        r"^funds?\s+investing\s+",
        r"^firms?\s+investing\s+",
        r"\bin\s+india$",
        r"\bfor\s+startups$",
        r"\bstartup\s+funding$",
    ]

    return any(
        re.search(
            pattern,
            normalized,
        )
        for pattern in generic_patterns
    )


def is_probable_organization_name(name: str) -> bool:
    if not name:
        return False

    name = clean_organization_name(name)

    if not name:
        return False

    if looks_like_generic_organization(name):
        return False

    words = name.split()

    if len(name) < 2 or len(name) > 100:
        return False

    if len(words) > 12:
        return False

    sentence_words = {
        "the",
        "top",
        "best",
        "list",
        "investing",
        "investors",
        "firms",
        "funds",
        "companies",
        "startups",
        "india",
        "guide",
        "directory",
        "ranking",
    }

    sentence_word_count = sum(
        1
        for word in words
        if normalize_name(word) in sentence_words
    )

    if sentence_word_count >= 3:
        return False

    return True


# ============================================================
# DOMAIN NAME
# ============================================================

def extract_domain_name(url: str) -> str:
    if not url:
        return ""

    try:
        parsed = urlparse(url)

        hostname = (
            parsed.netloc
            .lower()
            .replace("www.", "")
        )

        if not hostname:
            return ""

        domain_parts = hostname.split(".")

        if not domain_parts:
            return ""

        brand = domain_parts[0]

        if brand in {
            "blog",
            "news",
            "www",
            "invest",
            "about",
            "www2",
            "app",
            "mail",
        }:
            return ""

        return (
            brand
            .replace("-", " ")
            .replace("_", " ")
            .title()
        )

    except Exception:
        return ""


# ============================================================
# EXPLICIT ORGANIZATION EXTRACTION
# ============================================================

def extract_explicit_organization_from_content(
    content: str,
) -> Optional[str]:

    if not content:
        return None

    text = content[:16000].strip()

    patterns = [

        # Example:
        # "Blume Ventures is a venture capital firm"
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,80}?)\s+"
        r"is\s+(?:an?|the)\s+"
        r"(?:venture capital|vc|investment|angel|startup|"
        r"accelerator|incubator|private equity|impact)\b",

        # Example:
        # "Blume Ventures is one of..."
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,80}?)\s+"
        r"is\s+one\s+of\s+",

        # Example:
        # "Blume Ventures invests in..."
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,80}?)\s+"
        r"(?:invests|invested|investing)\s+"
        r"(?:in|into)\b",

        # Example:
        # "Blume Ventures focuses on..."
        r"\b([A-Z][A-Za-z0-9&.'’\- ]{1,80}?)\s+"
        r"(?:focuses|specializes|specialises)\s+on\b",

        # Example:
        # "Founded in 2010, Blume Ventures..."
        r"\b(?:founded|established|launched)\s+"
        r"(?:in\s+\d{4}\s*,?\s*)?"
        r"([A-Z][A-Za-z0-9&.'’\- ]{1,80}?)"
        r"(?:,|\s+is|\s+was)\b",
    ]

    for pattern in patterns:

        try:
            matches = re.findall(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

        except Exception:
            continue

        for match in matches:

            if isinstance(match, str):
                candidate = match

            elif isinstance(match, tuple) and match:
                candidate = match[0]

            else:
                continue

            candidate = clean_organization_name(
                candidate
            )

            if not is_probable_organization_name(
                candidate
            ):
                continue

            return candidate

    return None


# ============================================================
# EXA RESULT NORMALIZATION
# ============================================================

def normalize_exa_result(
    result: Any,
    category: str,
    search_query: str,
) -> Dict[str, Any]:

    title = getattr(
        result,
        "title",
        "",
    ) or ""

    url = getattr(
        result,
        "url",
        "",
    ) or ""

    text = getattr(
        result,
        "text",
        "",
    ) or ""

    author = getattr(
        result,
        "author",
        "",
    ) or ""

    published_date = getattr(
        result,
        "published_date",
        "",
    ) or ""

    return {
        "title": title,
        "content": text,
        "raw_content": text,
        "url": url,
        "author": author,
        "published_date": published_date,
        "score": 0.0,
        "category": category,
        "search_query": search_query,
        "source": "exa",
        "discovery_source": "exa",
    }


# ============================================================
# EXA SEARCH
# ============================================================

async def exa_search(
    search_query: str,
    category: str,
) -> List[Dict[str, Any]]:

    print(
        f"🟣 Exa discovery [{category}]: "
        f"{search_query}"
    )

    try:

        response = await asyncio.to_thread(
            exa_client.search,
            search_query,
            type="auto",
            num_results=EXA_MAX_RESULTS,
            contents={
                "text": {
                    "max_characters": 6000
                }
            },
        )

        results = []

        raw_results = getattr(
            response,
            "results",
            [],
        )

        for item in raw_results:

            normalized = normalize_exa_result(
                item,
                category,
                search_query,
            )

            if not normalized.get("url"):
                continue

            results.append(
                normalized
            )

        print(
            f"🟣 Exa returned "
            f"{len(results)} results"
        )

        return results

    except Exception as exc:

        print(
            f"⚠️ Exa search failed: "
            f"{exc}"
        )

        return []


# ============================================================
# TAVILY SEARCH
# ============================================================

async def tavily_search(
    search_query: str,
    category: str,
) -> List[Dict[str, Any]]:

    print(
        f"🔵 Tavily verification [{category}]: "
        f"{search_query}"
    )

    try:

        response = await asyncio.to_thread(
            tavily_client.search,
            query=search_query,
            search_depth="advanced",
            max_results=TAVILY_MAX_RESULTS,
            include_answer=False,
            include_raw_content=True,
        )

        results = []

        for result in response.get(
            "results",
            [],
        ):

            results.append({
                "title": result.get(
                    "title"
                ) or "",

                "content": result.get(
                    "content"
                ) or "",

                "raw_content": result.get(
                    "raw_content"
                ) or "",

                "url": result.get(
                    "url"
                ) or "",

                "score": result.get(
                    "score"
                ) or 0,

                "category": category,

                "search_query": search_query,

                "source": "tavily",

                "discovery_source": "tavily",
            })

        print(
            f"🔵 Tavily returned "
            f"{len(results)} results"
        )

        return results

    except Exception as exc:

        print(
            f"⚠️ Tavily search failed: "
            f"{exc}"
        )

        return []


# ============================================================
# QUERY DETECTION
# ============================================================

def detect_geography(
    query: str,
) -> str:

    query = normalize_text(query)

    if "india" in query:
        return "India"

    if "indian" in query:
        return "India"

    if "uae" in query:
        return "UAE"

    if "united arab emirates" in query:
        return "UAE"

    return "India"


def detect_stage(
    query: str,
) -> str:

    query = normalize_text(query)

    if (
        "pre-seed" in query
        or "pre seed" in query
    ):
        return "pre-seed"

    if "seed" in query:
        return "seed"

    if (
        "early stage" in query
        or "early-stage" in query
    ):
        return "early stage"

    return "early stage"


def detect_requested_categories(
    query: str,
) -> List[str]:

    query = normalize_text(query)

    categories = []

    category_aliases = {
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
            "lp",
            "limited partner",
            "limited partners",
            "fund of funds",
        ],
    }

    for category, aliases in category_aliases.items():

        if any(
            alias in query
            for alias in aliases
        ):
            categories.append(category)

    if not categories:
        categories = [
            "VC",
            "ANGEL",
            "ACCELERATOR",
            "INCUBATOR",
            "FAMILY_OFFICE",
            "FOUNDATION",
            "LP",
        ]

    return categories


# ============================================================
# ENTITY DISCOVERY QUERIES
# ============================================================

def build_entity_search_queries(
    user_query: str,
) -> List[Dict[str, str]]:

    geography = detect_geography(
        user_query
    )

    stage = detect_stage(
        user_query
    )

    categories = detect_requested_categories(
        user_query
    )

    queries = []

    for category in categories:

        if category == "VC":

            queries.extend([
                {
                    "category": "VC",
                    "query": (
                        f"{geography} venture capital firms "
                        f"investing in {stage} startups"
                    ),
                },

                {
                    "category": "VC",
                    "query": (
                        f"{geography} VC funds "
                        f"portfolio {stage} startups"
                    ),
                },
            ])

        elif category == "ANGEL":

            queries.extend([
                {
                    "category": "ANGEL",
                    "query": (
                        f"{geography} angel investors "
                        f"{stage} startup investments"
                    ),
                },

                {
                    "category": "ANGEL",
                    "query": (
                        f"{geography} angel networks "
                        f"startup portfolio investments"
                    ),
                },
            ])

        elif category == "ACCELERATOR":

            queries.extend([
                {
                    "category": "ACCELERATOR",
                    "query": (
                        f"{geography} startup accelerators "
                        f"investment funding {stage}"
                    ),
                },
            ])

        elif category == "INCUBATOR":

            queries.extend([
                {
                    "category": "INCUBATOR",
                    "query": (
                        f"{geography} startup incubators "
                        f"funding investment"
                    ),
                },
            ])

        elif category == "FAMILY_OFFICE":

            queries.extend([
                {
                    "category": "FAMILY_OFFICE",
                    "query": (
                        f"{geography} family offices "
                        f"startup venture investments"
                    ),
                },
            ])

        elif category == "FOUNDATION":

            queries.extend([
                {
                    "category": "FOUNDATION",
                    "query": (
                        f"{geography} foundations "
                        f"impact startup investments"
                    ),
                },
            ])

        elif category == "LP":

            queries.extend([
                {
                    "category": "LP",
                    "query": (
                        f"{geography} limited partners "
                        f"venture capital fund investments"
                    ),
                },
            ])

    # Remove duplicate queries.
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
# EXTRACT CANDIDATE ORGANIZATION
# ============================================================

def extract_candidate_from_result(
    result: Dict[str, Any],
) -> Optional[str]:

    title = (
        result.get("title")
        or ""
    ).strip()

    content = (
        result.get("content")
        or ""
    ).strip()

    raw_content = (
        result.get("raw_content")
        or ""
    ).strip()

    url = (
        result.get("url")
        or ""
    ).strip()

    # --------------------------------------------------------
    # 1. Explicit organization statement
    # --------------------------------------------------------

    explicit = (
        extract_explicit_organization_from_content(
            content
            + "\n"
            + raw_content[:10000]
        )
    )

    if explicit:
        return explicit

    # --------------------------------------------------------
    # 2. Exa/Tavily title
    # --------------------------------------------------------

    if title and not is_list_or_article(title):

        candidate = clean_organization_name(
            title
        )

        if is_probable_organization_name(
            candidate
        ):
            return candidate

    # --------------------------------------------------------
    # 3. Domain fallback
    # --------------------------------------------------------

    text = normalize_text(
        f"{title} "
        f"{content} "
        f"{raw_content[:6000]}"
    )

    investment_terms = [
        "venture capital",
        "venture fund",
        "vc fund",
        "angel investor",
        "angel investing",
        "invests in",
        "investing in",
        "portfolio",
        "startup investment",
        "startup funding",
        "accelerator",
        "incubator",
        "family office",
        "impact investor",
    ]

    if any(
        term in text
        for term in investment_terms
    ):

        domain_name = extract_domain_name(
            url
        )

        if is_probable_organization_name(
            domain_name
        ):
            return domain_name

    return None


# ============================================================
# DISCOVER CANDIDATES USING EXA
# ============================================================

async def discover_candidates(
    user_query: str,
) -> List[Dict[str, Any]]:

    queries = build_entity_search_queries(
        user_query
    )

    print(
        f"🧠 Generated "
        f"{len(queries)} discovery queries"
    )

    tasks = []

    for item in queries:

        tasks.append(
            exa_search(
                item["query"],
                item["category"],
            )
        )

    responses = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    all_results = []

    for response in responses:

        if isinstance(
            response,
            Exception,
        ):
            continue

        all_results.extend(
            response
        )

    print(
        f"🟣 Total Exa discovery results: "
        f"{len(all_results)}"
    )

    # --------------------------------------------------------
    # Extract organizations
    # --------------------------------------------------------

    candidates = {}

    for result in all_results:

        organization = (
            extract_candidate_from_result(
                result
            )
        )

        if not organization:
            continue

        organization = clean_organization_name(
            organization
        )

        if not is_probable_organization_name(
            organization
        ):
            continue

        normalized = normalize_name(
            organization
        )

        if not normalized:
            continue

        if normalized in candidates:

            existing = candidates[
                normalized
            ]

            existing[
                "discovery_count"
            ] += 1

            existing[
                "discovery_results"
            ].append(result)

        else:

            candidates[
                normalized
            ] = {
                "name": organization,
                "normalized_name": normalized,
                "discovery_count": 1,
                "discovery_results": [
                    result
                ],
                "category": result.get(
                    "category",
                    "VC",
                ),
                "source": "exa",
            }

    candidate_list = list(
        candidates.values()
    )

    # --------------------------------------------------------
    # Rank candidates
    # --------------------------------------------------------

    candidate_list.sort(
        key=lambda item: (
            item.get(
                "discovery_count",
                0,
            ),
            len(
                item.get(
                    "discovery_results",
                    [],
                )
            ),
        ),
        reverse=True,
    )

    candidate_list = candidate_list[
        :MAX_CANDIDATES_TO_VERIFY
    ]

    print(
        f"🎯 Candidates selected for "
        f"Tavily verification: "
        f"{len(candidate_list)}"
    )

    for candidate in candidate_list:

        print(
            f"   → {candidate['name']} "
            f"({candidate['category']})"
        )

    return candidate_list


# ============================================================
# BUILD VERIFICATION QUERIES
# ============================================================

def build_verification_queries(
    candidate_name: str,
    user_query: str,
    category: str,
) -> List[str]:

    geography = detect_geography(
        user_query
    )

    stage = detect_stage(
        user_query
    )

    queries = [
        (
            f'"{candidate_name}" '
            f"invests in {geography} startups "
            f"{stage}"
        ),

        (
            f'"{candidate_name}" '
            f"portfolio investments "
            f"{geography}"
        ),
    ]

    if category == "VC":

        queries.append(
            (
                f'"{candidate_name}" '
                f"venture capital portfolio "
                f"{geography}"
            )
        )

    elif category == "ANGEL":

        queries.append(
            (
                f'"{candidate_name}" '
                f"angel investor "
                f"{geography}"
            )
        )

    elif category == "ACCELERATOR":

        queries.append(
            (
                f'"{candidate_name}" '
                f"accelerator investment "
                f"{geography}"
            )
        )

    elif category == "INCUBATOR":

        queries.append(
            (
                f'"{candidate_name}" '
                f"incubator funding "
                f"{geography}"
            )
        )

    return list(
        dict.fromkeys(
            queries[
                :MAX_TAVILY_VERIFICATION_SEARCHES
            ]
        )
    )


# ============================================================
# VERIFY CANDIDATE WITH TAVILY
# ============================================================

async def verify_candidate(
    candidate: Dict[str, Any],
    user_query: str,
) -> Dict[str, Any]:

    candidate_name = candidate[
        "name"
    ]

    category = candidate.get(
        "category",
        "VC",
    )

    verification_queries = (
        build_verification_queries(
            candidate_name,
            user_query,
            category,
        )
    )

    tasks = []

    for query in verification_queries:

        tasks.append(
            tavily_search(
                query,
                category,
            )
        )

    responses = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    tavily_results = []

    for response in responses:

        if isinstance(
            response,
            Exception,
        ):
            continue

        tavily_results.extend(
            response
        )

    # --------------------------------------------------------
    # Match Tavily results to candidate
    # --------------------------------------------------------

    candidate_tokens = set(
        normalize_name(
            candidate_name
        ).split()
    )

    matched_results = []

    for result in tavily_results:

        text = normalize_text(
            f"{result.get('title', '')} "
            f"{result.get('content', '')} "
            f"{result.get('raw_content', '')[:6000]}"
        )

        # Strong candidate-name match.
        candidate_match = (
            normalize_name(
                candidate_name
            ) in normalize_name(text)
        )

        token_matches = sum(
            1
            for token in candidate_tokens
            if len(token) >= 3
            and token in text
        )

        if (
            candidate_match
            or token_matches >= max(
                1,
                len(candidate_tokens) // 2,
            )
        ):
            matched_results.append(
                result
            )

    # --------------------------------------------------------
    # Combine evidence
    # --------------------------------------------------------

    combined_text_parts = []

    for result in matched_results:

        combined_text_parts.append(
            result.get(
                "title",
                "",
            )
        )

        combined_text_parts.append(
            result.get(
                "content",
                "",
            )
        )

        combined_text_parts.append(
            result.get(
                "raw_content",
                "",
            )[:8000]
        )

    combined_text = normalize_text(
        " ".join(
            combined_text_parts
        )
    )

    # --------------------------------------------------------
    # Evidence checks
    # --------------------------------------------------------

    investment_terms = [
        "invest",
        "invested",
        "investing",
        "investment",
        "investments",
        "portfolio",
        "funding",
        "funded",
        "backs",
        "backed",
        "portfolio companies",
    ]

    geography_terms = [
        "india",
        "indian",
    ]

    has_investment_evidence = any(
        term in combined_text
        for term in investment_terms
    )

    has_geography_evidence = any(
        term in combined_text
        for term in geography_terms
    )

    # --------------------------------------------------------
    # Calculate verification score
    # --------------------------------------------------------

    verification_score = 0.0

    if matched_results:
        verification_score += 0.20

    if has_investment_evidence:
        verification_score += 0.30

    if has_geography_evidence:
        verification_score += 0.20

    if len(matched_results) >= 2:
        verification_score += 0.15

    if candidate.get(
        "discovery_count",
        0,
    ) >= 2:
        verification_score += 0.10

    # Exa + Tavily agreement.
    if matched_results:
        verification_score += 0.05

    verification_score = min(
        verification_score,
        0.99,
    )

    verified = (
        has_investment_evidence
        and has_geography_evidence
        and len(matched_results) > 0
    )

    # --------------------------------------------------------
    # Best evidence
    # --------------------------------------------------------

    best_result = None

    if matched_results:

        matched_results.sort(
            key=lambda result: float(
                result.get(
                    "score",
                    0,
                ) or 0
            ),
            reverse=True,
        )

        best_result = matched_results[0]

    return {
        **candidate,

        "verified": verified,

        "verification_score": round(
            verification_score,
            3,
        ),

        "verification_status": (
            "EXA_TAVILY_VERIFIED"
            if verified
            else "EXA_DISCOVERED"
        ),

        "providers": [
            "exa",
            "tavily",
        ],

        "tavily_results": matched_results,

        "best_result": best_result,

        "has_investment_evidence": (
            has_investment_evidence
        ),

        "has_geography_evidence": (
            has_geography_evidence
        ),

        "evidence_text": combined_text[
            :12000
        ],
    }


# ============================================================
# VERIFY ALL CANDIDATES
# ============================================================

async def verify_candidates(
    candidates: List[Dict[str, Any]],
    user_query: str,
) -> List[Dict[str, Any]]:

    if not candidates:
        return []

    tasks = []

    for candidate in candidates:

        tasks.append(
            verify_candidate(
                candidate,
                user_query,
            )
        )

    results = await asyncio.gather(
        *tasks,
        return_exceptions=True,
    )

    verified = []

    for result in results:

        if isinstance(
            result,
            Exception,
        ):
            print(
                f"⚠️ Candidate verification "
                f"failed: {result}"
            )
            continue

        verified.append(
            result
        )

    verified.sort(
        key=lambda item: (
            item.get(
                "verified",
                False,
            ),
            item.get(
                "verification_score",
                0,
            ),
            item.get(
                "discovery_count",
                0,
            ),
        ),
        reverse=True,
    )

    return verified


# ============================================================
# RELEVANCE SCORING
# ============================================================

def calculate_relevance(
    result: Dict[str, Any],
    category: str,
    original_query: str,
) -> float:

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

    raw_content = normalize_text(
        result.get(
            "raw_content",
            "",
        )[:6000]
    )

    text = (
        f"{title} "
        f"{content} "
        f"{raw_content}"
    )

    try:

        base_score = float(
            result.get(
                "score",
                0,
            ) or 0
        )

    except (
        TypeError,
        ValueError,
    ):

        base_score = 0.0

    score = base_score

    positive_terms = {
        "investor": 0.10,
        "investors": 0.10,
        "investing": 0.15,
        "investment": 0.15,
        "investments": 0.15,
        "venture capital": 0.20,
        "venture fund": 0.15,
        "vc fund": 0.15,
        "fund": 0.08,
        "portfolio": 0.12,
        "portfolio companies": 0.15,
        "startup funding": 0.12,
        "funding": 0.08,
        "backs startups": 0.15,
        "backing startups": 0.15,
        "early stage": 0.15,
        "early-stage": 0.15,
        "pre-seed": 0.20,
        "pre seed": 0.20,
        "seed stage": 0.15,
        "indian startups": 0.18,
        "indian startup": 0.15,
        "india": 0.10,
    }

    for term, weight in (
        positive_terms.items()
    ):

        if term in text:
            score += weight

    category_terms = {
        "VC": [
            "venture capital",
            "vc fund",
            "venture fund",
            "portfolio",
        ],

        "ANGEL": [
            "angel investor",
            "angel network",
            "angel fund",
            "angel investing",
        ],

        "ACCELERATOR": [
            "accelerator",
            "accelerator program",
        ],

        "INCUBATOR": [
            "incubator",
            "incubation",
        ],

        "FAMILY_OFFICE": [
            "family office",
            "family offices",
        ],

        "FOUNDATION": [
            "foundation",
            "impact investor",
            "impact investing",
        ],

        "LP": [
            "limited partner",
            "limited partners",
            "institutional investor",
            "fund of funds",
        ],
    }

    for term in category_terms.get(
        category,
        [],
    ):

        if term in text:
            score += 0.15

    negative_terms = {
        "job": 0.15,
        "jobs": 0.15,
        "career": 0.15,
        "careers": 0.15,
        "salary": 0.15,
        "hiring": 0.15,
        "recruitment": 0.15,
        "real estate": 0.15,
        "loan": 0.15,
        "insurance": 0.15,
        "stock price": 0.15,
        "share price": 0.15,
        "crypto price": 0.15,
    }

    for term, penalty in (
        negative_terms.items()
    ):

        if term in text:
            score -= penalty

    if not any(
        term in text
        for term in [
            "invest",
            "investing",
            "investment",
            "funding",
            "portfolio",
            "backed",
            "backs",
        ]
    ):
        score -= 0.25

    if not any(
        term in text
        for term in [
            "india",
            "indian",
        ]
    ):
        score -= 0.20

    return max(
        0.0,
        min(
            score,
            2.0,
        ),
    )


# ============================================================
# SOURCE QUALITY
# ============================================================

def calculate_source_quality(
    result: Dict[str, Any],
) -> float:

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

    url = result.get(
        "url",
        "",
    )

    score = 0.0

    if not is_list_or_article(
        title
    ):
        score += 0.20

    explicit_terms = [
        "is a venture capital firm",
        "is a venture fund",
        "is an investment firm",
        "we invest in",
        "we back",
        "our portfolio",
        "our investments",
        "our team",
        "investment thesis",
    ]

    for term in explicit_terms:

        if term in content:
            score += 0.15

    category_terms = [
        "venture capital",
        "angel investor",
        "accelerator",
        "incubator",
        "family office",
        "impact investor",
    ]

    for term in category_terms:

        if term in content:
            score += 0.05

    organization_terms = [
        "about us",
        "about",
        "portfolio",
        "team",
        "investment thesis",
        "our mission",
        "our approach",
    ]

    for term in organization_terms:

        if term in content:
            score += 0.04

    bad_domains = [
        "linkedin.com",
        "crunchbase.com",
        "tracxn.com",
        "medium.com",
        "forbes.com",
        "inc42.com",
        "yourstory.com",
    ]

    try:

        domain = (
            urlparse(
                url
            ).netloc.lower()
        )

    except Exception:

        domain = ""

    if any(
        bad_domain in domain
        for bad_domain in bad_domains
    ):
        score -= 0.10

    return max(
        0.0,
        min(
            score,
            1.0,
        ),
    )


# ============================================================
# CATEGORY DETECTION
# ============================================================

def detect_investor_category(
    text: str,
) -> str:

    text = normalize_text(
        text
    )

    scores = {
        "VC": 0,
        "ANGEL": 0,
        "ACCELERATOR": 0,
        "INCUBATOR": 0,
        "FAMILY_OFFICE": 0,
        "FOUNDATION": 0,
        "LP": 0,
    }

    category_keywords = {
        "VC": [
            "venture capital",
            "venture fund",
            "vc fund",
            "venture investor",
        ],

        "ANGEL": [
            "angel investor",
            "angel network",
            "angel fund",
            "angel investing",
        ],

        "ACCELERATOR": [
            "accelerator",
            "accelerator program",
        ],

        "INCUBATOR": [
            "incubator",
            "incubation",
        ],

        "FAMILY_OFFICE": [
            "family office",
            "family offices",
        ],

        "FOUNDATION": [
            "foundation",
            "impact foundation",
        ],

        "LP": [
            "limited partner",
            "limited partners",
            "institutional investor",
            "fund of funds",
        ],
    }

    for category, keywords in (
        category_keywords.items()
    ):

        for keyword in keywords:

            if keyword in text:
                scores[
                    category
                ] += 1

    best_category = max(
        scores,
        key=scores.get,
    )

    if scores[
        best_category
    ] == 0:

        return "INVESTOR"

    return best_category


# ============================================================
# INVESTMENT STAGE
# ============================================================

def detect_investment_stage(
    text: str,
) -> str:

    text = normalize_text(
        text
    )

    stages = []

    if (
        "pre-seed" in text
        or "pre seed" in text
    ):
        stages.append(
            "Pre-seed"
        )

    if "seed" in text:
        stages.append(
            "Seed"
        )

    if (
        "early stage" in text
        or "early-stage" in text
    ):
        stages.append(
            "Early Stage"
        )

    if not stages:
        return "Unknown"

    return " / ".join(
        dict.fromkeys(
            stages
        )
    )


# ============================================================
# CONFIDENCE
# ============================================================

def calculate_confidence(
    text: str,
    relevance: float,
    category: str,
    stage: str,
    verification_score: float,
    discovery_count: int,
) -> float:

    confidence = 0.25

    confidence += min(
        relevance * 0.20,
        0.20,
    )

    confidence += min(
        verification_score * 0.35,
        0.35,
    )

    if category != "INVESTOR":
        confidence += 0.08

    if stage != "Unknown":
        confidence += 0.07

    if discovery_count >= 2:
        confidence += 0.05

    if any(
        term in text
        for term in [
            "invested",
            "investing",
            "investment",
            "portfolio",
            "funding",
        ]
    ):
        confidence += 0.05

    if any(
        term in text
        for term in [
            "india",
            "indian",
        ]
    ):
        confidence += 0.05

    return round(
        min(
            confidence,
            0.99,
        ),
        2,
    )


# ============================================================
# BUILD FINAL INVESTOR
# ============================================================

def build_investor_from_candidate(
    candidate: Dict[str, Any],
    user_query: str,
) -> Optional[Dict[str, Any]]:

    candidate_name = candidate.get(
        "name",
        "",
    )

    if not is_probable_organization_name(
        candidate_name
    ):
        return None

    best_result = candidate.get(
        "best_result"
    )

    if not best_result:
        return None

    title = best_result.get(
        "title",
        "",
    )

    content = best_result.get(
        "content",
        "",
    )

    raw_content = best_result.get(
        "raw_content",
        "",
    )

    url = best_result.get(
        "url",
        "",
    )

    combined_text = normalize_text(
        f"{candidate_name} "
        f"{title} "
        f"{content} "
        f"{raw_content[:8000]}"
    )

    category = detect_investor_category(
        combined_text
    )

    # Prefer discovery category when
    # Tavily evidence is ambiguous.
    if category == "INVESTOR":

        category = candidate.get(
            "category",
            "INVESTOR",
        )

    stage = detect_investment_stage(
        combined_text
    )

    relevance = calculate_relevance(
        best_result,
        category,
        user_query,
    )

    source_quality = (
        calculate_source_quality(
            best_result
        )
    )

    verification_score = float(
        candidate.get(
            "verification_score",
            0,
        )
    )

    discovery_count = int(
        candidate.get(
            "discovery_count",
            1,
        )
    )

    confidence = calculate_confidence(
        combined_text,
        relevance,
        category,
        stage,
        verification_score,
        discovery_count,
    )

    # Strong verification bonus.
    if candidate.get(
        "verified",
        False,
    ):
        confidence = round(
            min(
                confidence + 0.08,
                0.99,
            ),
            2,
        )

    description = (
        content[:700]
        if content
        else ""
    )

    evidence = (
        content[:1500]
        if content
        else raw_content[:1500]
    )

    # --------------------------------------------------------
    # Provider status
    # --------------------------------------------------------

    if candidate.get(
        "verified",
        False,
    ):

        verification_status = (
            "EXA_TAVILY_VERIFIED"
        )

    else:

        verification_status = (
            "EXA_DISCOVERED"
        )

    return {

        "name": candidate_name,

        "normalized_name": normalize_name(
            candidate_name
        ),

        "type": category,

        "country": detect_geography(
            user_query
        ),

        "stage": stage,

        "description": description,

        "evidence": evidence,

        "confidence": confidence,

        "relevance": round(
            relevance,
            3,
        ),

        "source_quality": round(
            source_quality,
            3,
        ),

        "verification_score": round(
            verification_score,
            3,
        ),

        "verification_status": (
            verification_status
        ),

        "providers": [
            "exa",
            "tavily",
        ],

        "discovery_count": (
            discovery_count
        ),

        "url": url,

        "source": (
            "Exa + Tavily"
            if candidate.get(
                "verified",
                False,
            )
            else "Exa"
        ),

        "discovery_source": "Exa",

        "verification_source": (
            "Tavily"
            if candidate.get(
                "verified",
                False,
            )
            else None
        ),

        "search_query": user_query,
    }


# ============================================================
# BUILD FINAL RESULTS
# ============================================================

def build_investor_results(
    verified_candidates: List[
        Dict[str, Any]
    ],
    user_query: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:

    investors = []

    seen_names = set()

    for candidate in verified_candidates:

        # We want verified organizations first.
        # However, retain Exa discoveries when
        # they have meaningful evidence.
        if not candidate.get(
            "verified",
            False,
        ):

            if candidate.get(
                "verification_score",
                0,
            ) < 0.40:

                continue

        investor = (
            build_investor_from_candidate(
                candidate,
                user_query,
            )
        )

        if not investor:
            continue

        normalized_name = investor[
            "normalized_name"
        ]

        if normalized_name in seen_names:
            continue

        # Stronger final filtering.
        if (
            investor["confidence"] < 0.50
        ):
            continue

        if (
            investor["relevance"] < 0.35
        ):
            continue

        seen_names.add(
            normalized_name
        )

        investors.append(
            investor
        )

        if len(investors) >= limit:
            break

    # Highest confidence first.
    investors.sort(
        key=lambda item: (
            item.get(
                "verification_status",
                "",
            )
            == "EXA_TAVILY_VERIFIED",

            item.get(
                "confidence",
                0,
            ),

            item.get(
                "relevance",
                0,
            ),
        ),
        reverse=True,
    )

    return investors


# ============================================================
# COMPLETE SEARCH PIPELINE
# ============================================================

async def search_web(
    query: str,
) -> List[Dict[str, Any]]:

    print(
        "\n"
        "=================================================="
    )

    print(
        f"🔎 Connecting the Dots research: "
        f"{query}"
    )

    print(
        "=================================================="
    )

    # --------------------------------------------------------
    # STEP 1
    # Exa discovers organizations.
    # --------------------------------------------------------

    candidates = (
        await discover_candidates(
            query
        )
    )

    if not candidates:

        print(
            "⚠️ Exa found no candidates."
        )

        return []

    # --------------------------------------------------------
    # STEP 2
    # Tavily verifies candidates.
    # --------------------------------------------------------

    verified_candidates = (
        await verify_candidates(
            candidates,
            query,
        )
    )

    # --------------------------------------------------------
    # STEP 3
    # Convert into final organizations.
    # --------------------------------------------------------

    investors = (
        build_investor_results(
            verified_candidates,
            query,
            limit=50,
        )
    )

    print(
        "\n"
        "=================================================="
    )

    print(
        f"✅ Final organizations: "
        f"{len(investors)}"
    )

    print(
        "=================================================="
    )

    for investor in investors:

        print(
            f"   ✓ {investor['name']} "
            f"| {investor['type']} "
            f"| confidence="
            f"{investor['confidence']} "
            f"| status="
            f"{investor['verification_status']}"
        )

    return investors


# ============================================================
# RESEARCH
# ============================================================

async def research_query(
    query: str,
) -> Dict[str, Any]:

    investors = await search_web(
        query
    )

    if not investors:

        return {
            "answer": (
                "No verified investor "
                "organizations were found."
            ),

            "entities": [],

            "relationships": [],

            "opportunities": [],

            "investors": [],

            "citations": [],

            "providers": {
                "exa": True,
                "tavily": True,
            },
        }

    # --------------------------------------------------------
    # Category counts
    # --------------------------------------------------------

    category_counts = {}

    for investor in investors:

        category = investor.get(
            "type",
            "UNKNOWN",
        )

        category_counts[
            category
        ] = (
            category_counts.get(
                category,
                0,
            )
            + 1
        )

    # --------------------------------------------------------
    # Verification counts
    # --------------------------------------------------------

    verified_count = sum(
        1
        for investor in investors
        if investor.get(
            "verification_status"
        )
        == "EXA_TAVILY_VERIFIED"
    )

    exa_only_count = sum(
        1
        for investor in investors
        if investor.get(
            "verification_status"
        )
        == "EXA_DISCOVERED"
    )

    # --------------------------------------------------------
    # Human-readable answer
    # --------------------------------------------------------

    answer_parts = []

    answer_parts.append(
        f"Found {len(investors)} "
        f"potentially relevant investor "
        f"organizations for:"
    )

    answer_parts.append(
        f'"{query}"'
    )

    answer_parts.append("")

    answer_parts.append(
        "Provider pipeline:"
    )

    answer_parts.append(
        f"- Exa discovery: "
        f"{len(investors)} candidates"
    )

    answer_parts.append(
        f"- Exa + Tavily verified: "
        f"{verified_count}"
    )

    answer_parts.append(
        f"- Exa discovered only: "
        f"{exa_only_count}"
    )

    answer_parts.append("")

    if category_counts:

        answer_parts.append(
            "Categories found:"
        )

        for category, count in sorted(
            category_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        ):

            answer_parts.append(
                f"- {category}: {count}"
            )

        answer_parts.append("")

    answer_parts.append(
        "Organizations identified "
        "from search evidence:"
    )

    for investor in investors[:20]:

        answer_parts.append(
            f"- {investor['name']} "
            f"({investor['type']}, "
            f"{investor['stage']}) "
            f"[confidence: "
            f"{investor['confidence']}] "
            f"[{investor['verification_status']}]"
        )

    answer = "\n".join(
        answer_parts
    )

    # --------------------------------------------------------
    # Citations
    # --------------------------------------------------------

    citations = []

    seen_urls = set()

    for investor in investors:

        url = investor.get(
            "url",
            "",
        )

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(
            url
        )

        citations.append({

            "source": url,

            "title": investor.get(
                "name",
                "",
            ),

            "content": investor.get(
                "evidence",
                "",
            )[:500],

            "relevance": investor.get(
                "relevance",
                0,
            ),

            "confidence": investor.get(
                "confidence",
                0,
            ),

            "provider": investor.get(
                "source",
                "",
            ),

            "verification_status": (
                investor.get(
                    "verification_status",
                    "",
                )
            ),
        })

        if len(citations) >= 30:
            break

    return {

        "answer": answer,

        "entities": investors,

        "relationships": [],

        "opportunities": [],

        "investors": investors,

        "citations": citations,

        "providers": {
            "exa": True,
            "tavily": True,
        },

        "stats": {
            "total_organizations": len(
                investors
            ),

            "verified": verified_count,

            "exa_only": exa_only_count,

            "categories": category_counts,
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

    try:

        query = (
            request.query
            or ""
        ).strip()

        if not query:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Query cannot be empty."
                ),
            )

        print(
            f"🚀 Research request: "
            f"{query}"
        )

        results = await research_query(
            query
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

    except HTTPException:
        raise

    except Exception as exc:

        print(
            f"❌ Research error: "
            f"{exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ============================================================
# HEALTH
# ============================================================

@app.get(
    "/api/health"
)
async def health_check():

    return {

        "status": "healthy",

        "mode": "exa+tavily",

        "timestamp": datetime.utcnow()
        .isoformat(),

        "exa_configured": bool(
            EXA_API_KEY
        ),

        "tavily_configured": bool(
            TAVILY_API_KEY
        ),

        "providers": {

            "exa": {
                "configured": bool(
                    EXA_API_KEY
                ),

                "role": (
                    "entity discovery"
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
# ENTITY SEARCH
# ============================================================

@app.get(
    "/api/entities/search"
)
async def search_entities(
    query: str,
    limit: int = 10,
):

    try:

        query = (
            query
            or ""
        ).strip()

        if not query:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Query cannot be empty."
                ),
            )

        if limit < 1:
            limit = 1

        if limit > 100:
            limit = 100

        investors = await search_web(
            query
        )

        investors = investors[
            :limit
        ]

        return {

            "query": query,

            "entities": investors,

            "count": len(
                investors
            ),

            "providers": {
                "exa": True,
                "tavily": True,
            },
        }

    except HTTPException:
        raise

    except Exception as exc:

        print(
            f"❌ Entity search error: "
            f"{exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {

        "message": (
            "Connecting the Dots AI"
        ),

        "version": "2.0.0",

        "docs": "/docs",

        "health": "/api/health",

        "mode": "exa+tavily",

        "pipeline": (
            "Exa discovery -> "
            "Tavily verification -> "
            "entity scoring"
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