from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class EntityType(str, Enum):
    COMPANY = "COMPANY"
    PERSON = "PERSON"
    PRODUCT = "PRODUCT"
    PRODUCT_CATEGORY = "PRODUCT_CATEGORY"
    COUNTRY = "COUNTRY"
    CITY = "CITY"
    MARKET = "MARKET"
    DISTRIBUTOR = "DISTRIBUTOR"
    IMPORTER = "IMPORTER"
    RETAILER = "RETAILER"
    INVESTOR = "INVESTOR"
    FUND = "FUND"
    ACCELERATOR = "ACCELERATOR"
    INCUBATOR = "INCUBATOR"
    CUSTOMER = "CUSTOMER"
    SUPPLIER = "SUPPLIER"
    MANUFACTURER = "MANUFACTURER"

class RelationshipType(str, Enum):
    MANUFACTURES = "MANUFACTURES"
    EXPORTS_TO = "EXPORTS_TO"
    IMPORTS_FROM = "IMPORTS_FROM"
    DISTRIBUTED_BY = "DISTRIBUTED_BY"
    SUPPLIES = "SUPPLIES"
    SELLS_TO = "SELLS_TO"
    INVESTS_IN = "INVESTS_IN"
    PARTNERED_WITH = "PARTNERED_WITH"
    ACQUIRED_BY = "ACQUIRED_BY"
    SUBSIDIARY_OF = "SUBSIDIARY_OF"
    LOCATED_IN = "LOCATED_IN"
    OPERATES_IN = "OPERATES_IN"

class RelationshipStatus(str, Enum):
    VERIFIED = "VERIFIED"
    SUPPORTED = "SUPPORTED"
    INFERRED = "INFERRED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"

class EntitySchema(BaseModel):
    id: Optional[str] = None
    type: EntityType
    name: str
    normalized_name: str
    description: Optional[str] = None
    country: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class RelationshipSchema(BaseModel):
    id: Optional[str] = None
    source_entity_id: str
    target_entity_id: str
    relationship_type: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0)
    status: RelationshipStatus = RelationshipStatus.INFERRED
    evidence: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class DocumentChunkSchema(BaseModel):
    id: Optional[str] = None
    source_url: str
    content: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    entity_id: Optional[str] = None
    created_at: Optional[datetime] = None

class ResearchRunSchema(BaseModel):
    id: Optional[str] = None
    user_id: str
    query: str
    status: str = "PENDING"
    sources_count: int = 0
    entities_count: int = 0
    relationships_count: int = 0
    confidence_score: Optional[float] = None
    results: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)