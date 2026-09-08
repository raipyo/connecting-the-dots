import os
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx
from tavily import TavilyClient
import openai

# Load environment variables
load_dotenv()

app = FastAPI(title="Connecting the Dots AI")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "https://connecting-the-dots-backend.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize clients
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

if not OPENAI_API_KEY or not TAVILY_API_KEY:
    print("⚠️  WARNING: API keys not found! Using mock data...")
    USE_MOCK = True
else:
    USE_MOCK = False
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)
    tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

class ResearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = "anonymous"

class EntityExtraction(BaseModel):
    name: str
    type: str
    normalized_name: str
    description: Optional[str] = None
    country: Optional[str] = None
    confidence: float
    evidence: str

# ==================== REAL SEARCH FUNCTIONS ====================

async def search_web(query: str) -> List[Dict[str, Any]]:
    """Search the web using Tavily API"""
    if USE_MOCK:
        return get_mock_search_results(query)
    
    try:
        results = tavily_client.search(
            query=query,
            search_depth="advanced",
            max_results=10,
            include_answer=True,
            include_raw_content=True
        )
        
        # Process results
        processed_results = []
        
        # Add answer if available
        if results.get("answer"):
            processed_results.append({
                "title": "AI Answer",
                "content": results["answer"],
                "url": "",
                "relevance": 1.0,
                "source": "tavily_answer"
            })
        
        # Process search results
        for result in results.get("results", []):
            processed_results.append({
                "title": result.get("title", ""),
                "content": result.get("content", ""),
                "url": result.get("url", ""),
                "relevance": result.get("score", 0.5),
                "source": "web"
            })
        
        return processed_results
    except Exception as e:
        print(f"Search error: {e}")
        return get_mock_search_results(query)

async def extract_entities_with_openai(text: str, query: str) -> Dict[str, Any]:
    """Extract entities and relationships using OpenAI"""
    if USE_MOCK:
        return get_mock_extraction(query)
    
    try:
        prompt = f"""
        Analyze the following text and extract business entities and relationships.
        
        Query: {query}
        
        Text: {text}
        
        Extract:
        1. Companies (name, type, country, description)
        2. Relationships between entities (source, relationship_type, target, confidence)
        3. Business opportunities
        
        Return as JSON with this structure:
        {{
            "entities": [
                {{
                    "name": "Company name",
                    "type": "COMPANY|DISTRIBUTOR|RETAILER|MANUFACTURER",
                    "normalized_name": "normalized name",
                    "description": "description",
                    "country": "country",
                    "confidence": 0.95,
                    "evidence": "evidence text"
                }}
            ],
            "relationships": [
                {{
                    "source": "source entity name",
                    "relationship": "EXPORTS_TO|MANUFACTURES|SUPPLIES|DISTRIBUTED_BY",
                    "target": "target entity name",
                    "confidence": 0.9,
                    "status": "VERIFIED|SUPPORTED|INFERRED",
                    "evidence": "evidence text"
                }}
            ],
            "opportunities": [
                {{
                    "description": "opportunity description",
                    "confidence": 0.8,
                    "entities": ["entity1", "entity2"],
                    "actionable": true,
                    "potential_value": "potential value description"
                }}
            ]
        }}
        """
        
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a business intelligence expert. Extract entities and relationships from business text."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"Extraction error: {e}")
        return get_mock_extraction(query)

async def research_query(query: str) -> Dict[str, Any]:
    """Main research function combining search and extraction"""
    # Step 1: Search the web
    search_results = await search_web(query)
    
    if not search_results:
        return {
            "answer": "No results found. Please try a different query.",
            "entities": [],
            "relationships": [],
            "opportunities": [],
            "citations": []
        }
    
    # Step 2: Combine search results text
    combined_text = "\n\n".join([
        f"Source: {r.get('title', 'Unknown')}\n{r.get('content', '')}"
        for r in search_results[:5]  # Use top 5 results
    ])
    
    # Step 3: Extract entities using OpenAI
    extraction = await extract_entities_with_openai(combined_text, query)
    
    # Step 4: Generate answer
    answer = f"Based on research for: {query}\n\n"
    if extraction.get("entities"):
        answer += f"Found {len(extraction['entities'])} entities and {len(extraction.get('relationships', []))} relationships.\n\n"
        
        # Add entity details
        for entity in extraction.get("entities", [])[:5]:
            answer += f"• {entity.get('name')} ({entity.get('type', 'Unknown')}) - {entity.get('country', 'Location unknown')}\n"
    
    # Step 5: Prepare response
    return {
        "answer": answer,
        "entities": extraction.get("entities", []),
        "relationships": extraction.get("relationships", []),
        "opportunities": extraction.get("opportunities", []),
        "citations": [
            {
                "source": r.get("url", r.get("source", "Unknown")),
                "content": r.get("content", "")[:200] + "...",
                "relevance": r.get("relevance", 0.5)
            }
            for r in search_results[:5]
        ]
    }

# ==================== MOCK DATA (Fallback) ====================

def get_mock_search_results(query: str) -> List[Dict[str, Any]]:
    """Mock search results when API keys are not available"""
    query_lower = query.lower()
    
    # Determine country from query
    country = "Global"
    if "usa" in query_lower or "america" in query_lower:
        country = "USA"
    elif "india" in query_lower:
        country = "India"
    elif "uae" in query_lower or "dubai" in query_lower:
        country = "UAE"
    elif "europe" in query_lower:
        country = "Europe"
    
    return [
        {
            "title": f"Business Overview - {country}",
            "content": f"Companies in {country} are expanding their operations. Several businesses are looking for international partners and distributors.",
            "url": "mock-source.com",
            "relevance": 0.9,
            "source": "mock"
        }
    ]

def get_mock_extraction(query: str) -> Dict[str, Any]:
    """Mock extraction when OpenAI is not available"""
    query_lower = query.lower()
    
    # Determine country from query
    country = "Global"
    if "usa" in query_lower or "america" in query_lower:
        country = "USA"
        companies = ["TechCorp America", "Global Solutions US"]
    elif "india" in query_lower:
        country = "India"
        companies = ["EcoPack India", "GreenWrap Solutions"]
    elif "uae" in query_lower or "dubai" in query_lower:
        country = "UAE"
        companies = ["Dubai Trading Co", "Emirates Logistics"]
    else:
        companies = ["Sample Company"]
    
    return {
        "entities": [
            {
                "name": companies[0],
                "type": "COMPANY",
                "normalized_name": companies[0],
                "description": f"Leading company in {country}",
                "country": country,
                "confidence": 0.85,
                "evidence": "Mock evidence"
            }
        ],
        "relationships": [],
        "opportunities": []
    }

# ==================== API ENDPOINTS ====================

@app.post("/api/research")
async def perform_research(request: ResearchRequest):
    """Perform research with real search or mock data"""
    try:
        # Check if we should use mock data
        if USE_MOCK:
            print("⚠️  Using mock data (API keys not configured)")
            results = get_mock_extraction(request.query)
            return {
                "research_run_id": str(uuid.uuid4()),
                "status": "completed",
                "results": {
                    "query": request.query,
                    "response": {
                        "answer": f"Research results for: {request.query}\n\n⚠️ Using mock data. Add OPENAI_API_KEY and TAVILY_API_KEY to .env file for real results.",
                        **results,
                        "citations": [{"source": "mock", "content": "Mock data", "relevance": 0.5}]
                    },
                    "sources": [{"type": "mock", "content": "Mock source", "relevance": 0.5}]
                }
            }
        
        # Real search
        print(f"🔍 Researching: {request.query}")
        results = await research_query(request.query)
        
        return {
            "research_run_id": str(uuid.uuid4()),
            "status": "completed",
            "results": {
                "query": request.query,
                "response": results,
                "sources": [
                    {
                        "type": "web",
                        "content": "Real search results",
                        "relevance": 0.9
                    }
                ]
            }
        }
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "mode": "mock" if USE_MOCK else "real",
        "timestamp": datetime.utcnow().isoformat(),
        "openai_configured": bool(OPENAI_API_KEY),
        "tavily_configured": bool(TAVILY_API_KEY)
    }

@app.get("/api/entities/search")
async def search_entities(query: str, limit: int = 10):
    """Search for entities"""
    # This would query your PostgreSQL database
    # For now, return mock results
    return {
        "entities": [
            {"id": "1", "name": "Sample Entity", "type": "COMPANY", "country": "Global"}
        ]
    }

@app.get("/")
async def root():
    return {
        "message": "Connecting the Dots AI",
        "docs": "/docs",
        "health": "/api/health",
        "mode": "mock" if USE_MOCK else "real"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)