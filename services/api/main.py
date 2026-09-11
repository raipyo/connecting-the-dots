import os
import re
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from tavily import TavilyClient


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

app = FastAPI(title="Connecting the Dots AI")


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
# TAVILY
# ============================================================

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if not TAVILY_API_KEY:
    raise RuntimeError(
        "TAVILY_API_KEY is not configured. "
        "Add it to your .env file."
    )

tavily_client = TavilyClient(
    api_key=TAVILY_API_KEY
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
        "VC fund",
        "venture fund",
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
        "LP investor",
        "institutional investor",
        "fund of funds",
    ],
}


# ============================================================
# SEARCH QUERY GENERATION
# ============================================================

def generate_search_queries(user_query: str) -> List[Dict[str, str]]:
    """
    Turn one broad user query into multiple focused searches.

    This is the most important improvement over the original
    implementation.
    """

    query = user_query.lower()

    queries = []

    # --------------------------------------------------------
    # Detect geography
    # --------------------------------------------------------

    geography = "India"

    if "india" in query or "indian" in query:
        geography = "India"

    # --------------------------------------------------------
    # Detect investment stage
    # --------------------------------------------------------

    stage = "early stage"

    if "pre-seed" in query or "pre seed" in query:
        stage = "pre-seed"

    elif "seed" in query:
        stage = "seed"

    elif "early stage" in query or "early-stage" in query:
        stage = "early stage"

    # --------------------------------------------------------
    # VC
    # --------------------------------------------------------

    queries.append({
        "category": "VC",
        "query": (
            f"venture capital firms investing in {geography} "
            f"startups at {stage}"
        ),
    })

    queries.append({
        "category": "VC",
        "query": (
            f"{geography} VC funds "
            f"pre-seed seed early stage startup investors"
        ),
    })

    queries.append({
        "category": "VC",
        "query": (
            f"venture capital investors "
            f"backing {geography} startups {stage}"
        ),
    })

    queries.append({
        "category": "VC",
        "query": (
            f"{geography} venture capital firm "
            f"{stage} investments portfolio"
        ),
    })

    queries.append({
        "category": "VC",
        "query": (
            f"{geography} VC fund "
            f"{stage} portfolio companies"
        ),
    })

    queries.append({
        "category": "VC",
        "query": (
            f"site:.vc {geography} startup investor "
            f"{stage}"
        ),
    })

    queries.append({
        "category": "VC",
        "query": (
            f"venture capital firm India "
            f"our portfolio {stage}"
        ),
    })

    # --------------------------------------------------------
    # ANGELS
    # --------------------------------------------------------

    queries.append({
        "category": "ANGEL",
        "query": (
            f"angel investors investing in {geography} "
            f"startups {stage}"
        ),
    })

    queries.append({
        "category": "ANGEL",
        "query": (
            f"angel investor networks in {geography} "
            f"startup funding pre-seed seed"
        ),
    })

    queries.append({
        "category": "ANGEL",
        "query": (
            f"{geography} angel investors "
            f"portfolio startups early stage"
        ),
    })

    queries.append({
        "category": "ANGEL",
        "query": (
            f"angel investor India "
            f"portfolio startups {stage}"
        ),
    })

    queries.append({
        "category": "ANGEL",
        "query": (
            f"angel network India "
            f"investment portfolio startups"
        ),
    })

    # --------------------------------------------------------
    # ACCELERATORS
    # --------------------------------------------------------

    queries.append({
        "category": "ACCELERATOR",
        "query": (
            f"startup accelerators in {geography} "
            f"investing pre-seed seed startups"
        ),
    })

    queries.append({
        "category": "ACCELERATOR",
        "query": (
            f"{geography} accelerators "
            f"provide funding investment startups"
        ),
    })

    queries.append({
        "category": "ACCELERATOR",
        "query": (
            f"startup accelerator India "
            f"portfolio investment funding"
        ),
    })

    queries.append({
        "category": "ACCELERATOR",
        "query": (
            f"India accelerator program "
            f"invests in startups"
        ),
    })

    # --------------------------------------------------------
    # INCUBATORS
    # --------------------------------------------------------

    queries.append({
        "category": "INCUBATOR",
        "query": (
            f"startup incubators in {geography} "
            f"provide funding investment"
        ),
    })

    queries.append({
        "category": "INCUBATOR",
        "query": (
            f"{geography} technology incubators "
            f"early stage startup funding"
        ),
    })

    queries.append({
        "category": "INCUBATOR",
        "query": (
            f"startup incubator India "
            f"portfolio funding investment"
        ),
    })

    # --------------------------------------------------------
    # FAMILY OFFICES
    # --------------------------------------------------------

    queries.append({
        "category": "FAMILY_OFFICE",
        "query": (
            f"family offices investing in {geography} "
            f"startups early stage"
        ),
    })

    queries.append({
        "category": "FAMILY_OFFICE",
        "query": (
            f"{geography} family offices "
            f"venture capital startup investments"
        ),
    })

    # --------------------------------------------------------
    # FOUNDATIONS / IMPACT
    # --------------------------------------------------------

    queries.append({
        "category": "FOUNDATION",
        "query": (
            f"foundations investing in {geography} "
            f"startups impact early stage"
        ),
    })

    queries.append({
        "category": "FOUNDATION",
        "query": (
            f"impact investors funding {geography} "
            f"early stage startups"
        ),
    })

    # --------------------------------------------------------
    # LP / INSTITUTIONAL
    # --------------------------------------------------------

    queries.append({
        "category": "LP",
        "query": (
            f"institutional investors limited partners "
            f"investing in {geography} venture capital funds"
        ),
    })

    queries.append({
        "category": "LP",
        "query": (
            f"LP investors backing {geography} "
            f"venture capital funds"
        ),
    })

    return queries


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(text: Any) -> str:
    if text is None:
        return ""

    if not isinstance(text, str):
        text = str(text)

    text = text.lower()
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_url(url: str) -> str:
    """
    Normalize URLs so multiple pages from the same website
    are easier to deduplicate.
    """

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


def normalize_name(name: str) -> str:
    name = normalize_text(name)

    name = re.sub(
        r"[^a-z0-9\s]",
        "",
        name
    )

    return re.sub(
        r"\s+",
        " ",
        name
    ).strip()


# ============================================================
# RELEVANCE SCORING
# ============================================================

def calculate_relevance(
    result: Dict[str, Any],
    category: str,
    original_query: str,
) -> float:
    """
    Score a Tavily result based on investor relevance.

    Tavily score is useful, but should NOT be the only signal.
    """

    title = normalize_text(
        result.get("title", "") or ""
    )

    content = normalize_text(
        result.get("content", "") or ""
    )

    text = f"{title} {content}"

    try:
        tavily_score = float(
            result.get("score") or 0
        )
    except (TypeError, ValueError):
        tavily_score = 0.0

    # Start with Tavily score.
    score = tavily_score

    # --------------------------------------------------------
    # Strong positive signals
    # --------------------------------------------------------

    positive_terms = {
        "investor": 0.18,
        "investors": 0.18,
        "investing": 0.20,
        "investment": 0.18,
        "investments": 0.18,
        "venture capital": 0.25,
        "venture fund": 0.20,
        "vc fund": 0.20,
        "fund": 0.10,
        "portfolio": 0.12,
        "portfolio companies": 0.15,
        "startup funding": 0.15,
        "funding": 0.10,
        "backs startups": 0.18,
        "backing startups": 0.18,
        "early stage": 0.20,
        "early-stage": 0.20,
        "pre-seed": 0.25,
        "pre seed": 0.25,
        "seed stage": 0.22,
        "seed": 0.08,
        "india": 0.12,
        "indian startups": 0.20,
        "indian startup": 0.18,
    }

    for term, weight in positive_terms.items():

        if term in text:
            score += weight

    # --------------------------------------------------------
    # Category-specific signals
    # --------------------------------------------------------

    category_terms = {
        "VC": [
            "venture capital",
            "vc fund",
            "venture fund",
            "venture partner",
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
            "startup accelerator",
        ],

        "INCUBATOR": [
            "incubator",
            "incubation",
            "startup incubator",
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

    for term in category_terms.get(category, []):

        if term in text:
            score += 0.20

    # --------------------------------------------------------
    # Negative signals
    # --------------------------------------------------------

    negative_terms = {
        "job": 0.15,
        "jobs": 0.15,
        "career": 0.15,
        "careers": 0.15,
        "salary": 0.15,
        "hiring": 0.15,
        "recruitment": 0.15,
        "real estate": 0.20,
        "loan": 0.20,
        "insurance": 0.15,
        "stock price": 0.15,
        "share price": 0.15,
        "crypto price": 0.15,
    }

    for term, penalty in negative_terms.items():

        if term in text:
            score -= penalty

    # --------------------------------------------------------
    # Require actual investment language
    # --------------------------------------------------------

    investment_evidence = [
        "invest",
        "investing",
        "investment",
        "funding",
        "funded",
        "portfolio",
        "backs",
        "backed",
    ]

    if not any(
        term in text
        for term in investment_evidence
    ):
        score -= 0.30

    # --------------------------------------------------------
    # India relevance
    # --------------------------------------------------------

    india_terms = [
        "india",
        "indian",
        "india-focused",
        "india focused",
    ]

    if not any(
        term in text
        for term in india_terms
    ):
        score -= 0.25

    # --------------------------------------------------------
    # Early-stage relevance
    # --------------------------------------------------------

    stage_terms = [
        "early stage",
        "early-stage",
        "pre-seed",
        "pre seed",
        "seed stage",
        "seed-stage",
    ]

    if any(
        term in text
        for term in stage_terms
    ):
        score += 0.20

    return max(
        0.0,
        min(score, 2.0)
    )


# ============================================================
# EXTRACT INVESTOR NAME
# ============================================================

def is_list_or_article(title: str) -> bool:
    """
    Determine whether a search result title is likely to be
    an article, ranking, directory, listicle, or search page
    rather than an individual organization.
    """

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

    # Question-style titles are almost never organizations.
    if title.endswith("?"):
        return True

    # Very long titles are usually article headings.
    if len(title.split()) > 12:
        return True

    return False

def calculate_source_quality(
    result: Dict[str, Any],
) -> float:
    """
    Estimate whether the result is likely to be an
    organization page rather than an article/listicle.
    """

    title = normalize_text(
        result.get("title") or ""
    )

    content = normalize_text(
        result.get("content") or ""
    )

    url = result.get("url") or ""

    score = 0.0

    # Official-looking title.
    if not is_list_or_article(title):
        score += 0.20

    # Strong organization language.
    explicit_terms = [
        "is a venture capital firm",
        "is a venture fund",
        "is an investment firm",
        "we invest in",
        "we back",
        "our portfolio",
        "our investments",
        "our team",
    ]

    for term in explicit_terms:
        if term in content:
            score += 0.15

    # Strong category language.
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

    # Organization/about language.
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

    # Penalize obvious third-party list/article pages.
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
        domain = urlparse(url).netloc.lower()
    except Exception:
        domain = ""

    if any(
        bad_domain in domain
        for bad_domain in bad_domains
    ):
        score -= 0.10

    return max(
        0.0,
        min(score, 1.0)
    )


# ============================================================
# SEARCH TAVILY
# ============================================================

async def search_web(
    query: str
) -> List[Dict[str, Any]]:
    """
    Run multiple targeted Tavily searches.
    """

    search_queries = generate_search_queries(
        query
    )

    all_results = []

    print(
        f"🔎 Generated "
        f"{len(search_queries)} targeted searches"
    )

    # --------------------------------------------------------
    # Execute searches
    # --------------------------------------------------------

    for search in search_queries:

        category = search["category"]

        search_query = search["query"]

        print(
            f"🔍 [{category}] {search_query}"
        )

        try:

            response = tavily_client.search(
                query=search_query,

                # Advanced gives better content extraction.
                search_depth="advanced",

                # 10 results per search.
                max_results=10,

                # We want raw results, not Tavily's single
                # generated answer.
                include_answer=False,

                include_raw_content=True,
            )

            for result in response.get(
                "results",
                []
            ):

                all_results.append({
                    "title": result.get("title") or "",
                    "content": result.get("content") or "",
                    "raw_content": result.get("raw_content") or "",
                    "url": result.get("url") or "",
                    "score": result.get("score") or 0,
                    "category": category,
                    "search_query": search_query,
                    "source": "tavily",
                })

        except Exception as e:

            print(
                f"⚠️ Tavily search failed "
                f"for [{category}]: {e}"
            )

    print(
        f"📊 Raw Tavily results: "
        f"{len(all_results)}"
    )

    # ========================================================
    # DEDUPLICATION
    # ========================================================

    unique_results = {}

    for result in all_results:

        url = result.get(
            "url",
            ""
        )

        domain = normalize_url(url)

        title = normalize_text(
            result.get(
                "title",
                ""
            )
        )

        # Prefer URL/domain as the primary identifier.
        key = (
            url.lower().strip()
            if url
            else title
        )

        if not key:
            continue

        # If the same page appears multiple times,
        # keep the strongest version.
        if key not in unique_results:

            unique_results[key] = result

        else:

            existing = unique_results[key]

            if result.get(
                "score",
                0
            ) > existing.get(
                "score",
                0
            ):

                unique_results[key] = result

    results = list(
        unique_results.values()
    )

    print(
        f"📊 Unique results: "
        f"{len(results)}"
    )

    # ========================================================
    # SCORE RESULTS
    # ========================================================

    for index, result in enumerate(results):
        try:
            try:
                result["relevance"] = calculate_relevance(
                    result,
                    result.get("category") or "VC",
                    query,
                )
            except Exception as e:
                print(
                    f"⚠️ Failed to score result #{index}: {e}"
                )
                print(
                    f"   URL: {result.get('url') or ''}"
                )
                print(
                    f"   Title: {result.get('title') or ''}"
                )

                result["relevance"] = 0.0
        except Exception as e:
            print(
                f"⚠️ Failed to process result #{index}: {e}"
            )
            print(
                f"   Title: {result.get('title') or ''}"
            )
            print(
                f"   URL: {result.get('url') or ''}"
            )
            continue

    # ========================================================
    # SORT
    # ========================================================

    results.sort(
        key=lambda x: x.get(
            "relevance",
            0
        ),
        reverse=True,
    )

    return results


# ============================================================
# BUILD INVESTOR RESULTS
# ============================================================

def build_investor_results(
    results: List[Dict[str, Any]],
    limit: int = 50,
) -> List[Dict[str, Any]]:

    investors = []

    seen_names = set()

    for result in results:

        title = result.get("title") or ""
        content = result.get("content") or ""
        raw_content = result.get("raw_content") or ""
        url = result.get("url") or ""
        relevance = float(
            result.get(
                "relevance",
                0
            )
        )

        # ----------------------------------------------------
        # Reject weak search results
        # ----------------------------------------------------

        if relevance < 0.65:
            continue

        # ----------------------------------------------------
        # Reject article/listicle headings
        # ----------------------------------------------------

        if is_list_or_article(title):
            continue

        # ----------------------------------------------------
        # Combined evidence
        # ----------------------------------------------------

        text = normalize_text(
            f"{title} {content} {raw_content[:8000]}"
        )

        # ----------------------------------------------------
        # Require investment evidence
        # ----------------------------------------------------

        investment_terms = [
            "invest",
            "investing",
            "investment",
            "investments",
            "portfolio",
            "funding",
            "funded",
            "backs startups",
            "backing startups",
            "invests in",
            "investing in",
        ]

        has_investment_evidence = any(
            term in text
            for term in investment_terms
        )

        if not has_investment_evidence:
            continue

        # ----------------------------------------------------
        # Require India relevance
        # ----------------------------------------------------

        india_terms = [
            "india",
            "indian",
            "india-focused",
            "india focused",
        ]

        has_india_evidence = any(
            term in text
            for term in india_terms
        )

        if not has_india_evidence:
            continue

        # ----------------------------------------------------
        # Extract ACTUAL organization
        # ----------------------------------------------------

        name = extract_organization_from_result(
            result
        )

        if not name:
            continue

        name = clean_organization_name(
            name
        )

        normalized_name = normalize_name(
            name
        )

        if not normalized_name:
            continue

        if looks_like_generic_organization(
            name
        ):
            continue

        # ----------------------------------------------------
        # Deduplicate organizations, not URLs
        # ----------------------------------------------------

        if normalized_name in seen_names:
            continue

        # ----------------------------------------------------
        # Category / stage
        # ----------------------------------------------------

        category = detect_investor_category(
            text
        )

        stage = detect_investment_stage(
            text
        )

        # ----------------------------------------------------
        # Source quality
        # ----------------------------------------------------

        source_quality = calculate_source_quality(
            result
        )

        # ----------------------------------------------------
        # Confidence
        # ----------------------------------------------------

        confidence = calculate_confidence(
            text,
            relevance,
            category,
            stage,
        )

        # Increase confidence when the page itself
        # explicitly identifies an organization.
        explicit_org = (
            extract_explicit_organization_from_content(
                content + "\n" + raw_content[:8000]
            )
        )

        if explicit_org:
            confidence += 0.10

        # Source quality contributes to confidence.
        confidence += source_quality * 0.10

        confidence = round(
            min(confidence, 0.99),
            2
        )

        seen_names.add(
            normalized_name
        )

        # ----------------------------------------------------
        # Description
        # ----------------------------------------------------

        description = (
            content[:500]
            if content
            else ""
        )

        evidence = (
            content[:1000]
            if content
            else raw_content[:1000]
        )

        investors.append({

            # Actual organization name.
            "name": name,

            # Frontend already expects this.
            "normalized_name": normalized_name,

            "type": category,

            "country": "India",

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

            "url": url,

            "source": "Tavily",

            "search_query": result.get(
                "search_query",
                ""
            ),
        })

        if len(investors) >= limit:
            break

    return investors

# ============================================================
# ORGANIZATION EXTRACTION
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
}


def clean_organization_name(name: str) -> str:
    """
    Clean an extracted organization name without destroying
    legitimate company names.
    """

    if not name:
        return ""

    name = name.strip()

    # Remove surrounding punctuation.
    name = re.sub(r'^[\s\-–—|:;,]+', '', name)
    name = re.sub(r'[\s\-–—|:;,]+$', '', name)

    # Remove common sentence endings.
    name = re.sub(
        r'\s+(is|are|was|were|has|have|provides|offers|invests).*$',
        '',
        name,
        flags=re.IGNORECASE,
    )

    # Collapse whitespace.
    name = re.sub(r'\s+', ' ', name).strip()

    return name


def looks_like_generic_organization(name: str) -> bool:
    """
    Reject names that are actually search headings,
    article titles, categories, or generic descriptions.
    """

    normalized = normalize_name(name)

    if not normalized:
        return True

    if normalized in GENERIC_ORGANIZATION_NAMES:
        return True

    generic_patterns = [
        r'^top\s+',
        r'^best\s+',
        r'^list\s+of\s+',
        r'^list\s*:',
        r'^ranking',
        r'^rankings',
        r'^guide\s+to\s+',
        r'^directory',
        r'^how\s+to\s+',
        r'^where\s+to\s+',
        r'^who\s+',
        r'^investors?\s+in\s+',
        r'^venture\s+capital\s+firms?\s+',
        r'^venture\s+capital\s+investors?\s+',
        r'^venture\s+capital\s+funds?\s+',
        r'^seed\s+investors?\s+',
        r'^seed\s+funds?\s+',
        r'^angel\s+investors?\s+',
        r'^startup\s+investors?\s+',
        r'^startup\s+funding',
        r'^funds?\s+investing\s+',
        r'^firms?\s+investing\s+',
        r'\bin\s+india$',
        r'\bfor\s+startups$',
        r'\bstartup\s+funding$',
    ]

    return any(
        re.search(pattern, normalized)
        for pattern in generic_patterns
    )


def is_probable_organization_name(name: str) -> bool:
    """
    Determine whether a candidate looks like an actual
    organization rather than an article/search heading.
    """

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

    # Reject obvious sentence-like candidates.
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


def extract_domain_name(url: str) -> str:
    """
    Extract a human-readable brand candidate from the domain.

    Example:
        https://www.blume.vc/portfolio
        -> Blume

    This is only a fallback. It is NOT considered strong
    evidence by itself.
    """

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

        # Handle domains such as:
        # accel.com
        # blume.vc
        # example.co.in
        if brand in {
            "blog",
            "news",
            "www",
            "invest",
            "about",
            "www2",
        }:
            return ""

        return brand.replace("-", " ").replace("_", " ").title()

    except Exception:
        return ""


def extract_explicit_organization_from_content(
    content: str,
) -> Optional[str]:
    """
    Extract organization names from explicit sentences in
    the page content.

    Examples:

        "Blume Ventures is a venture capital firm..."

        "Accel is a global venture capital firm..."

        "Peak XV Partners invests in early-stage startups..."

    This is much safer than using the search result title.
    """

    if not content:
        return None

    # Limit the amount of text we inspect.
    text = content[:12000].strip()

    patterns = [
        # "Blume Ventures is a venture capital firm"
        r'\b([A-Z][A-Za-z0-9&.\'’\- ]{1,80}?)\s+'
        r'is\s+(?:an?|the)\s+'
        r'(?:venture capital|vc|investment|angel|startup|'
        r'accelerator|incubator|private equity|impact)\b',

        # "Blume Ventures is one of..."
        r'\b([A-Z][A-Za-z0-9&.\'’\- ]{1,80}?)\s+'
        r'is\s+one\s+of\s+',

        # "Blume Ventures invests in..."
        r'\b([A-Z][A-Za-z0-9&.\'’\- ]{1,80}?)\s+'
        r'(?:invests|invested|investing)\s+'
        r'(?:in|into)\b',

        # "Blume Ventures focuses on..."
        r'\b([A-Z][A-Za-z0-9&.\'’\- ]{1,80}?)\s+'
        r'(?:focuses|specializes|specialises)\s+on\b',

        # "Founded in 2010, Blume Ventures..."
        r'\b(?:founded|established|launched)\s+'
        r'(?:in\s+\d{4}\s*,?\s*)?'
        r'([A-Z][A-Za-z0-9&.\'’\- ]{1,80}?)'
        r'(?:,|\s+is|\s+was)\b',
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

            candidate = clean_organization_name(candidate)

            if not is_probable_organization_name(candidate):
                continue

            normalized = normalize_name(candidate)

            if normalized in GENERIC_ORGANIZATION_NAMES:
                continue

            return candidate

    return None


def extract_organization_from_result(
    result: Dict[str, Any]
) -> Optional[str]:
    """
    Extract the actual organization represented by a
    search result.

    Priority:

    1. Explicit organization statement in page content
    2. Strong organization-style title
    3. Domain brand as a weak fallback

    We NEVER blindly trust a generic search-result heading.
    """

    title = (
        result.get("title", "")
        or ""
    ).strip()

    content = (
        result.get("content", "")
        or ""
    ).strip()

    raw_content = (
        result.get("raw_content", "")
        or ""
    ).strip()

    url = (
        result.get("url", "")
        or ""
    ).strip()

    # --------------------------------------------------------
    # 1. Never use obvious article/listicle titles.
    # --------------------------------------------------------

    if is_list_or_article(title):
        title_candidate = None
    else:
        title_candidate = clean_organization_name(
            title
        )

    # --------------------------------------------------------
    # 2. Strongest signal:
    # explicit organization name in page content.
    # --------------------------------------------------------

    combined_content = (
        content
        + "\n"
        + raw_content[:10000]
    )

    explicit_name = (
        extract_explicit_organization_from_content(
            combined_content
        )
    )

    if explicit_name:
        return explicit_name

    # --------------------------------------------------------
    # 3. Use title only if it looks like an actual
    # organization name.
    # --------------------------------------------------------

    if (
        title_candidate
        and is_probable_organization_name(
            title_candidate
        )
    ):
        return title_candidate

    # --------------------------------------------------------
    # 4. Weak fallback:
    # derive a brand from the domain.
    #
    # Only use this when the page contains strong
    # investment evidence.
    # --------------------------------------------------------

    text = normalize_text(
        f"{title} {content} {raw_content[:5000]}"
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

    has_investment_evidence = any(
        term in text
        for term in investment_terms
    )

    if has_investment_evidence:
        domain_name = extract_domain_name(url)

        if is_probable_organization_name(
            domain_name
        ):
            return domain_name

    return None

def detect_investor_category(
    text: str
) -> str:

    text = normalize_text(text)

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

    for category, keywords in category_keywords.items():

        for keyword in keywords:

            if keyword in text:
                scores[category] += 1

    best_category = max(
        scores,
        key=scores.get
    )

    if scores[best_category] == 0:
        return "INVESTOR"

    return best_category

def detect_investment_stage(
    text: str
) -> str:

    text = normalize_text(text)

    stages = []

    if (
        "pre-seed" in text
        or "pre seed" in text
    ):
        stages.append("Pre-seed")

    if "seed" in text:
        stages.append("Seed")

    if (
        "early stage" in text
        or "early-stage" in text
    ):
        stages.append("Early Stage")

    if not stages:
        return "Unknown"

    # Remove duplicates while preserving order.
    return " / ".join(
        dict.fromkeys(stages)
    )

def calculate_confidence(
    text: str,
    relevance: float,
    category: str,
    stage: str,
) -> float:

    confidence = 0.30

    # Tavily relevance
    confidence += min(
        relevance * 0.30,
        0.30
    )

    # Investor category
    if category != "INVESTOR":
        confidence += 0.15

    # Stage evidence
    if stage != "Unknown":
        confidence += 0.10

    # Investment evidence
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
        confidence += 0.10

    # India evidence
    if any(
        term in text
        for term in [
            "india",
            "indian",
        ]
    ):
        confidence += 0.05

    return round(
        min(confidence, 0.99),
        2
    )


# ============================================================
# RESEARCH
# ============================================================

async def research_query(
    query: str
) -> Dict[str, Any]:

    # --------------------------------------------------------
    # Search
    # --------------------------------------------------------

    search_results = await search_web(
        query
    )

    if not search_results:

        return {
            "answer": (
                "No relevant investor results "
                "were found."
            ),

            "entities": [],

            "relationships": [],

            "opportunities": [],

            "investors": [],

            "citations": [],
        }

    # --------------------------------------------------------
    # Build investors
    # --------------------------------------------------------

    investors = build_investor_results(
        search_results,
        limit=50,
    )

    # --------------------------------------------------------
    # Group by category
    # --------------------------------------------------------

    category_counts = {}

    for investor in investors:

        category = investor.get(
            "type",
            "UNKNOWN"
        )

        category_counts[category] = (
            category_counts.get(
                category,
                0
            ) + 1
        )

    # --------------------------------------------------------
    # Generate human-readable answer
    # --------------------------------------------------------

    answer_parts = []

    answer_parts.append(
        f"Found {len(investors)} potentially "
        f"relevant investor organizations for:"
    )

    answer_parts.append(
        f'"{query}"'
    )

    answer_parts.append("")

    if category_counts:

        answer_parts.append(
            "Categories found:"
        )

        for category, count in sorted(
            category_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        ):

            answer_parts.append(
                f"- {category}: {count}"
            )

    answer_parts.append("")

    answer_parts.append(
        "Organizations identified from the search evidence:"
    )

    for investor in investors[:15]:
        answer_parts.append(
            f"- {investor['name']} "
            f"({investor['type']}, "
            f"{investor['stage']}) "
            f"[confidence: "
            f"{investor['confidence']}]"
        )

    answer = "\n".join(
        answer_parts
    )

    # --------------------------------------------------------
    # Citations
    # --------------------------------------------------------

    citations = []

    for result in search_results[:30]:

        url = result.get(
            "url",
            ""
        )

        if not url:
            continue

        citations.append({
            "source": url,

            "title": result.get(
                "title",
                ""
            ),

            "content": result.get(
                "content",
                ""
            )[:500],

            "relevance": round(
                result.get(
                    "relevance",
                    0
                ),
                3,
            ),

            "category": result.get(
                "category",
                ""
            ),
        })

    # --------------------------------------------------------
    # Return
    # --------------------------------------------------------

    return {
        "answer": answer,

        "entities": investors,

        "relationships": [],

        "opportunities": [],

        "investors": investors,

        "citations": citations,
    }


# ============================================================
# API
# ============================================================

@app.post("/api/research")
async def perform_research(
    request: ResearchRequest
):

    try:

        print(
            f"🚀 Research request: "
            f"{request.query}"
        )

        results = await research_query(
            request.query
        )

        return {
            "research_run_id": str(
                uuid.uuid4()
            ),

            "status": "completed",

            "results": {
                "query": request.query,

                "response": results,

                "sources": results.get(
                    "citations",
                    []
                ),
            },
        }

    except Exception as e:

        print(
            f"❌ Research error: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
async def health_check():

    return {
        "status": "healthy",

        "mode": "tavily",

        "timestamp": datetime.utcnow().isoformat(),

        "tavily_configured": bool(
            TAVILY_API_KEY
        ),
    }


# ============================================================
# ENTITY SEARCH
# ============================================================

@app.get("/api/entities/search")
async def search_entities(
    query: str,
    limit: int = 10,
):

    try:

        results = await search_web(
            query
        )

        investors = build_investor_results(
            results,
            limit=limit,
        )

        return {
            "entities": investors
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {
        "message": "Connecting the Dots AI",

        "docs": "/docs",

        "health": "/api/health",

        "mode": "tavily",
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