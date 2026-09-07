import openai
import numpy as np
from typing import List, Union
from functools import lru_cache

class EmbeddingService:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.dimension = 1536  # For text-embedding-3-small
    
    def get_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text"""
        response = self.client.embeddings.create(
            model=self.model,
            input=text
        )
        return response.data[0].embedding
    
    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts in batch"""
        response = self.client.embeddings.create(
            model=self.model,
            input=texts
        )
        return [data.embedding for data in response.data]
    
    @lru_cache(maxsize=1000)
    def get_embedding_cached(self, text: str) -> List[float]:
        """Cached version for frequently accessed texts"""
        return self.get_embedding(text)