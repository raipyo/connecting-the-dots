import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from pgvector.sqlalchemy import Vector
import uuid
from datetime import datetime

Base = declarative_base()

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/connecting_dots")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Entity(Base):
    __tablename__ = "entities"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(String(50), nullable=False)  # COMPANY, PERSON, PRODUCT, etc.
    name = Column(String(500), nullable=False)
    normalized_name = Column(String(500), index=True)
    description = Column(Text)
    country = Column(String(100))
    metadata = Column(JSON)
    embedding = Column(Vector(1536))  # OpenAI embedding dimension
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Relationship(Base):
    __tablename__ = "relationships"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"))
    target_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"))
    relationship_type = Column(String(100), nullable=False)
    confidence = Column(Float)
    status = Column(String(50))  # VERIFIED, SUPPORTED, INFERRED, UNVERIFIED, CONFLICTING
    evidence = Column(JSON)  # Store evidence references
    metadata = Column(JSON)
    embedding = Column(Vector(1536))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    source_entity = relationship("Entity", foreign_keys=[source_entity_id])
    target_entity = relationship("Entity", foreign_keys=[target_entity_id])

class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_url = Column(String(1000))
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536))
    metadata = Column(JSON)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ResearchRun(Base):
    __tablename__ = "research_runs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255))
    query = Column(Text)
    status = Column(String(50))  # PENDING, PROCESSING, COMPLETED, FAILED
    sources_count = Column(Integer, default=0)
    entities_count = Column(Integer, default=0)
    relationships_count = Column(Integer, default=0)
    confidence_score = Column(Float)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    results = Column(JSON)
    embedding = Column(Vector(1536))