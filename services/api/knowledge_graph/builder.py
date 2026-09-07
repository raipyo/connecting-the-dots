from typing import List, Dict, Any
import json
from sqlalchemy.orm import Session
from ..core.database import Entity, Relationship, SessionLocal

class KnowledgeGraphBuilder:
    def __init__(self):
        self.db = SessionLocal()
    
    def build_graph_from_extractions(
        self,
        extractions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Build knowledge graph from AI extractions
        """
        entities_added = 0
        relationships_added = 0
        
        for extraction in extractions:
            # Extract entities
            for entity_data in extraction.get("entities", []):
                entity = self._create_entity(entity_data)
                if entity:
                    entities_added += 1
            
            # Extract relationships
            for rel_data in extraction.get("relationships", []):
                relationship = self._create_relationship(rel_data)
                if relationship:
                    relationships_added += 1
        
        return {
            "entities_added": entities_added,
            "relationships_added": relationships_added
        }
    
    def _create_entity(self, data: Dict[str, Any]) -> Entity:
        """Create or update entity from extracted data"""
        existing = self.db.query(Entity).filter(
            Entity.normalized_name == data.get("normalized_name"),
            Entity.type == data.get("type")
        ).first()
        
        if existing:
            # Update existing entity
            existing.description = data.get("description", existing.description)
            existing.country = data.get("country", existing.country)
            existing.metadata = data.get("metadata", existing.metadata)
            self.db.commit()
            return existing
        
        entity = Entity(
            type=data.get("type"),
            name=data.get("name"),
            normalized_name=data.get("normalized_name"),
            description=data.get("description"),
            country=data.get("country"),
            metadata=data.get("metadata", {})
        )
        
        self.db.add(entity)
        self.db.commit()
        return entity
    
    def _create_relationship(self, data: Dict[str, Any]) -> Relationship:
        """Create relationship between entities"""
        source_entity = self.db.query(Entity).filter(
            Entity.normalized_name == data.get("source")
        ).first()
        
        target_entity = self.db.query(Entity).filter(
            Entity.normalized_name == data.get("target")
        ).first()
        
        if not source_entity or not target_entity:
            return None
        
        relationship = Relationship(
            source_entity_id=source_entity.id,
            target_entity_id=target_entity.id,
            relationship_type=data.get("relationship"),
            confidence=data.get("confidence", 0.7),
            status=data.get("status", "INFERRED"),
            evidence=data.get("evidence", {}),
            metadata=data.get("metadata", {})
        )
        
        self.db.add(relationship)
        self.db.commit()
        return relationship