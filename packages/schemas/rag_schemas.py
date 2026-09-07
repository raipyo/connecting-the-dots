from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class SearchSource(str, Enum):
    VECTOR = "vector"
    KEYWORD = "keyword"
    GRAPH = "graph"
    WEB = "web"
    HYBRID = "hybrid"

class RetrievalResult(BaseModel):
    id: str
    content: str
    metadata: Dict[str, Any]
    similarity: float = Field(ge=0.0, le=1.0)
    source: SearchSource
    entity_id: Optional[str] = None
    relationship_id: Optional[str] = None

class EntityExtraction(BaseModel):
    name: str
    type: str
    normalized_name: str
    description: Optional[str] = None
    country: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RelationshipExtraction(BaseModel):
    source: str
    relationship: str
    target: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: str = "INFERRED"
    evidence: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class OpportunityDetection(BaseModel):
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    entities: List[str]
    actionable: bool = True
    potential_value: Optional[str] = None
    evidence: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RAGResponse(BaseModel):
    answer: str
    entities: List[EntityExtraction]
    relationships: List[RelationshipExtraction]
    opportunities: List[OpportunityDetection]
    citations: List[Dict[str, Any]]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    confidence_overall: float = Field(ge=0.0, le=1.0)