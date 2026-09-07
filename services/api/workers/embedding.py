from celery import Celery
from typing import List, Dict, Any
import logging
from ..core.database import SessionLocal, DocumentChunk, Entity
from ..core.embeddings import EmbeddingService

app = Celery('connecting_dots', broker='redis://localhost:6379/0')

@app.task
def process_document_embeddings(document_ids: List[str]):
    """
    Process document chunks and generate embeddings
    """
    embedding_service = EmbeddingService()
    db = SessionLocal()
    
    chunks = db.query(DocumentChunk).filter(
        DocumentChunk.id.in_(document_ids),
        DocumentChunk.embedding.is_(None)
    ).all()
    
    for chunk in chunks:
        try:
            embedding = embedding_service.get_embedding(chunk.content)
            chunk.embedding = embedding
            db.commit()
            logging.info(f"Processed embedding for chunk {chunk.id}")
        except Exception as e:
            logging.error(f"Failed to process chunk {chunk.id}: {e}")
            db.rollback()

@app.task
def process_batch_embeddings(chunk_ids: List[str], batch_size: int = 100):
    """
    Process embeddings in batches for efficiency
    """
    embedding_service = EmbeddingService()
    db = SessionLocal()
    
    # Process in batches
    for i in range(0, len(chunk_ids), batch_size):
        batch = chunk_ids[i:i+batch_size]
        
        chunks = db.query(DocumentChunk).filter(
            DocumentChunk.id.in_(batch)
        ).all()
        
        texts = [chunk.content for chunk in chunks]
        
        try:
            embeddings = embedding_service.get_embeddings_batch(texts)
            
            for chunk, embedding in zip(chunks, embeddings):
                chunk.embedding = embedding
            
            db.commit()
            logging.info(f"Processed batch {i//batch_size + 1} of {len(chunks)} chunks")
        except Exception as e:
            logging.error(f"Failed to process batch: {e}")
            db.rollback()

@app.task
def cleanup_embeddings():
    """
    Clean up old or unused embeddings
    """
    db = SessionLocal()
    
    # Remove embeddings older than 30 days that haven't been accessed
    # Or implement your cleanup logic
    pass