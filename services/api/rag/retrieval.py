from sqlalchemy import text
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import json
from ..core.database import SessionLocal, DocumentChunk, Entity, Relationship
from ..core.embeddings import EmbeddingService

class RetrievalService:
    def __init__(self, embedding_service: EmbeddingService):
        self.embedding_service = embedding_service
        self.db = SessionLocal()
    
    def vector_similarity_search(
        self, 
        query: str, 
        table: str = "document_chunks",
        limit: int = 10,
        threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Perform vector similarity search using pgvector"""
        query_embedding = self.embedding_service.get_embedding(query)
        
        sql = f"""
        SELECT 
            id,
            content,
            metadata,
            1 - (embedding <=> :embedding) as similarity
        FROM {table}
        WHERE 1 - (embedding <=> :embedding) > :threshold
        ORDER BY embedding <=> :embedding
        LIMIT :limit
        """
        
        result = self.db.execute(
            text(sql),
            {
                "embedding": query_embedding,
                "threshold": threshold,
                "limit": limit
            }
        )
        
        return [
            {
                "id": row[0],
                "content": row[1],
                "metadata": row[2],
                "similarity": row[3]
            }
            for row in result
        ]
    
    def hybrid_search(
        self,
        query: str,
        limit: int = 10,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search combining vector similarity and keyword search
        """
        query_embedding = self.embedding_service.get_embedding(query)
        
        # Vector similarity search
        vector_results = self.vector_similarity_search(query, limit=limit)
        
        # Keyword search using PostgreSQL full-text search
        keyword_results = self.keyword_search(query, limit=limit)
        
        # Combine results with weighted scoring
        combined = self._combine_results(
            vector_results, 
            keyword_results,
            vector_weight,
            keyword_weight
        )
        
        return combined[:limit]
    
    def keyword_search(
        self,
        query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Perform keyword search using PostgreSQL full-text search"""
        sql = """
        SELECT 
            id,
            content,
            metadata,
            ts_rank(to_tsvector('english', content), plainto_tsquery('english', :query)) as rank
        FROM document_chunks
        WHERE to_tsvector('english', content) @@ plainto_tsquery('english', :query)
        ORDER BY rank DESC
        LIMIT :limit
        """
        
        result = self.db.execute(
            text(sql),
            {"query": query, "limit": limit}
        )
        
        return [
            {
                "id": row[0],
                "content": row[1],
                "metadata": row[2],
                "similarity": row[3]
            }
            for row in result
        ]
    
    def graph_search(
        self,
        query: str,
        relationship_types: List[str] = None,
        depth: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Search the knowledge graph for entities and relationships
        """
        # First find relevant entities via vector search
        entity_results = self.vector_similarity_search(
            query,
            table="entities",
            limit=5
        )
        
        if not entity_results:
            return []
        
        entity_ids = [r["id"] for r in entity_results]
        
        # Get relationships for these entities
        sql = """
        WITH RECURSIVE graph_cte AS (
            -- Initial entities
            SELECT 
                e.id as entity_id,
                e.name as entity_name,
                e.type as entity_type,
                NULL::uuid as source_id,
                NULL::uuid as target_id,
                NULL::text as rel_type,
                0 as depth
            FROM entities e
            WHERE e.id = ANY(:entity_ids)
            
            UNION ALL
            
            -- Traverse relationships
            SELECT 
                CASE 
                    WHEN r.source_entity_id = g.entity_id THEN r.target_entity_id
                    ELSE r.source_entity_id
                END as entity_id,
                e.name as entity_name,
                e.type as entity_type,
                r.source_entity_id as source_id,
                r.target_entity_id as target_id,
                r.relationship_type as rel_type,
                g.depth + 1
            FROM graph_cte g
            JOIN relationships r ON (
                r.source_entity_id = g.entity_id OR 
                r.target_entity_id = g.entity_id
            )
            JOIN entities e ON (
                e.id = r.source_entity_id OR 
                e.id = r.target_entity_id
            )
            WHERE g.depth < :depth
            AND e.id != g.entity_id
        )
        SELECT DISTINCT * FROM graph_cte
        """
        
        result = self.db.execute(
            text(sql),
            {
                "entity_ids": entity_ids,
                "depth": depth
            }
        )
        
        return [
            {
                "entity_id": row[0],
                "entity_name": row[1],
                "entity_type": row[2],
                "source_id": row[3],
                "target_id": row[4],
                "relationship_type": row[5],
                "depth": row[6]
            }
            for row in result
        ]
    
    def combined_retrieval(
        self,
        query: str,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Combined retrieval from vector, graph, and web search
        """
        results = {
            "vector_results": self.vector_similarity_search(query, limit=limit//2),
            "graph_results": self.graph_search(query, depth=2),
            "keyword_results": self.keyword_search(query, limit=limit//2),
            "web_results": []  # Populated by web search service
        }
        
        return results