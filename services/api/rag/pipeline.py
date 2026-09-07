from typing import List, Dict, Any
import json
from datetime import datetime
from ..core.database import SessionLocal, DocumentChunk, Entity, Relationship, ResearchRun
from ..core.embeddings import EmbeddingService
from .retrieval import RetrievalService
from .generation import GenerationService

class RAGPipeline:
    def __init__(
        self,
        embedding_service: EmbeddingService,
        retrieval_service: RetrievalService,
        generation_service: GenerationService
    ):
        self.embedding_service = embedding_service
        self.retrieval_service = retrieval_service
        self.generation_service = generation_service
        self.db = SessionLocal()
    
    def process_research_query(self, query: str, user_id: str) -> Dict[str, Any]:
        """
        Main entry point for processing a research query through the RAG pipeline
        """
        # Create research run record
        research_run = ResearchRun(
            user_id=user_id,
            query=query,
            status="PROCESSING",
            started_at=datetime.utcnow()
        )
        self.db.add(research_run)
        self.db.commit()
        
        try:
            # Step 1: Retrieve relevant information
            retrieval_results = self.retrieval_service.combined_retrieval(query)
            
            # Step 2: Process and augment retrieved information
            processed_results = self._process_retrieval_results(retrieval_results)
            
            # Step 3: Generate response with citations
            response = self.generation_service.generate_response(
                query=query,
                context=processed_results
            )
            
            # Step 4: Update research run with results
            research_run.status = "COMPLETED"
            research_run.completed_at = datetime.utcnow()
            research_run.sources_count = len(processed_results.get("sources", []))
            research_run.entities_count = len(processed_results.get("entities", []))
            research_run.relationships_count = len(processed_results.get("relationships", []))
            research_run.results = response
            research_run.embedding = self.embedding_service.get_embedding(query)
            
            self.db.commit()
            
            return {
                "query": query,
                "response": response,
                "research_run_id": str(research_run.id),
                "sources": processed_results.get("sources", []),
                "entities": processed_results.get("entities", []),
                "relationships": processed_results.get("relationships", []),
                "opportunities": processed_results.get("opportunities", [])
            }
            
        except Exception as e:
            research_run.status = "FAILED"
            research_run.metadata = {"error": str(e)}
            self.db.commit()
            raise
    
    def _process_retrieval_results(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Process and structure retrieval results"""
        processed = {
            "sources": [],
            "entities": [],
            "relationships": [],
            "opportunities": []
        }
        
        # Process vector search results
        for chunk in results.get("vector_results", []):
            processed["sources"].append({
                "type": "document",
                "content": chunk["content"],
                "metadata": chunk["metadata"],
                "relevance": chunk["similarity"]
            })
        
        # Process graph results
        for relationship in results.get("graph_results", []):
            processed["relationships"].append({
                "source": relationship["entity_name"],
                "source_type": relationship["entity_type"],
                "relationship_type": relationship["relationship_type"],
                "target": "Related Entity",  # Would need to fetch actual target
                "confidence": relationship.get("confidence", 0.7)
            })
        
        # Process keyword results
        for chunk in results.get("keyword_results", []):
            processed["sources"].append({
                "type": "document",
                "content": chunk["content"],
                "relevance": chunk["similarity"]
            })
        
        return processed