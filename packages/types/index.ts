// Entity Types
export enum EntityType {
  COMPANY = 'COMPANY',
  PERSON = 'PERSON',
  PRODUCT = 'PRODUCT',
  PRODUCT_CATEGORY = 'PRODUCT_CATEGORY',
  COUNTRY = 'COUNTRY',
  CITY = 'CITY',
  MARKET = 'MARKET',
  DISTRIBUTOR = 'DISTRIBUTOR',
  IMPORTER = 'IMPORTER',
  RETAILER = 'RETAILER',
  INVESTOR = 'INVESTOR',
  FUND = 'FUND',
  ACCELERATOR = 'ACCELERATOR',
  INCUBATOR = 'INCUBATOR',
  CUSTOMER = 'CUSTOMER',
  SUPPLIER = 'SUPPLIER',
  MANUFACTURER = 'MANUFACTURER',
}

// Relationship Types
export enum RelationshipType {
  MANUFACTURES = 'MANUFACTURES',
  EXPORTS_TO = 'EXPORTS_TO',
  IMPORTS_FROM = 'IMPORTS_FROM',
  DISTRIBUTED_BY = 'DISTRIBUTED_BY',
  SUPPLIES = 'SUPPLIES',
  SELLS_TO = 'SELLS_TO',
  INVESTS_IN = 'INVESTS_IN',
  PARTNERED_WITH = 'PARTNERED_WITH',
  ACQUIRED_BY = 'ACQUIRED_BY',
  SUBSIDIARY_OF = 'SUBSIDIARY_OF',
  LOCATED_IN = 'LOCATED_IN',
  OPERATES_IN = 'OPERATES_IN',
}

export enum RelationshipStatus {
  VERIFIED = 'VERIFIED',
  SUPPORTED = 'SUPPORTED',
  INFERRED = 'INFERRED',
  UNVERIFIED = 'UNVERIFIED',
  CONFLICTING = 'CONFLICTING',
}

// Entity Interface
export interface Entity {
  id?: string;
  type: EntityType;
  name: string;
  normalizedName: string;
  description?: string;
  country?: string;
  metadata: Record<string, any>;
  embedding?: number[];
  createdAt?: Date;
  updatedAt?: Date;
}

// Relationship Interface
export interface Relationship {
  id?: string;
  sourceEntityId: string;
  targetEntityId: string;
  relationshipType: RelationshipType;
  confidence: number;
  status: RelationshipStatus;
  evidence: Record<string, any>;
  metadata: Record<string, any>;
  embedding?: number[];
  createdAt?: Date;
  updatedAt?: Date;
}

// Document Chunk Interface
export interface DocumentChunk {
  id?: string;
  sourceUrl: string;
  content: string;
  embedding?: number[];
  metadata: Record<string, any>;
  entityId?: string;
  createdAt?: Date;
}

// Research Run Interface
export interface ResearchRun {
  id?: string;
  userId: string;
  query: string;
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
  sourcesCount: number;
  entitiesCount: number;
  relationshipsCount: number;
  confidenceScore?: number;
  results: Record<string, any>;
  startedAt?: Date;
  completedAt?: Date;
  embedding?: number[];
  metadata: Record<string, any>;
}

// RAG Request/Response Interfaces
export interface RAGRequest {
  query: string;
  userId?: string;
  options?: {
    maxSources?: number;
    includeGraph?: boolean;
    includeWeb?: boolean;
    confidenceThreshold?: number;
  };
}

export interface RAGResponse {
  answer: string;
  entities: EntityExtraction[];
  relationships: RelationshipExtraction[];
  opportunities: OpportunityDetection[];
  citations: Citation[];
  metadata: Record<string, any>;
  confidenceOverall: number;
}

export interface EntityExtraction {
  name: string;
  type: string;
  normalizedName: string;
  description?: string;
  country?: string;
  confidence: number;
  evidence: string;
  metadata: Record<string, any>;
}

export interface RelationshipExtraction {
  source: string;
  relationship: string;
  target: string;
  confidence: number;
  status: string;
  evidence: string;
  metadata: Record<string, any>;
}

export interface OpportunityDetection {
  description: string;
  confidence: number;
  entities: string[];
  actionable: boolean;
  potentialValue?: string;
  evidence: string;
  metadata: Record<string, any>;
}

export interface Citation {
  source: string;
  content: string;
  relevance: number;
  sourceType?: string;
  retrievedAt?: Date;
}