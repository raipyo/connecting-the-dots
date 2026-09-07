import openai
from typing import List, Dict, Any
import json

class GenerationService:
    def __init__(self, api_key: str, model: str = "gpt-4-turbo-preview"):
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
    
    def generate_response(
        self,
        query: str,
        context: Dict[str, Any],
        include_citations: bool = True
    ) -> Dict[str, Any]:
        """
        Generate a response using the retrieved context with citations
        """
        # Prepare the prompt with context
        prompt = self._build_prompt(query, context)
        
        # Generate response
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Add citations
        if include_citations:
            result["citations"] = self._generate_citations(context)
        
        return result
    
    def _get_system_prompt(self) -> str:
        return """
        You are Connecting the Dots AI, a research and relationship discovery system.
        
        Your job is to analyze provided information and generate:
        1. A clear, concise answer to the user's query
        2. The key entities identified (companies, products, people, etc.)
        3. The relationships discovered between these entities
        4. Business opportunities or insights identified
        5. Confidence levels for each claim
        6. Distinguish between verified information and AI inference
        
        Always cite your sources and indicate confidence levels.
        
        Return your response as a JSON object with the following structure:
        {
            "answer": "Clear, concise answer",
            "entities": [
                {
                    "name": "Entity name",
                    "type": "COMPANY|PERSON|PRODUCT|etc",
                    "confidence": 0.0-1.0,
                    "evidence": "Supporting evidence"
                }
            ],
            "relationships": [
                {
                    "source": "Entity A",
                    "relationship": "EXPORTS_TO|MANUFACTURES|etc",
                    "target": "Entity B",
                    "confidence": 0.0-1.0,
                    "status": "VERIFIED|INFERRED|SUPPORTED",
                    "evidence": "Supporting evidence"
                }
            ],
            "opportunities": [
                {
                    "description": "Opportunity description",
                    "confidence": 0.0-1.0,
                    "entities": ["Entity A", "Entity B"],
                    "actionable": true
                }
            ],
            "metadata": {
                "sources_used": ["source1", "source2"],
                "confidence_overall": 0.0-1.0
            }
        }
        """
    
    def _build_prompt(self, query: str, context: Dict[str, Any]) -> str:
        """Build the prompt with context"""
        context_text = json.dumps(context, indent=2)
        
        return f"""
        User Query: {query}
        
        Retrieved Context:
        {context_text}
        
        Please analyze this information and provide:
        1. Direct answer to the query
        2. Key entities found
        3. Relationships between entities
        4. Business opportunities or insights
        5. Confidence levels with evidence
        
        Distinguish between verified information and AI inference.
        """
    
    def _generate_citations(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate citations from context"""
        citations = []
        
        for source in context.get("sources", []):
            citations.append({
                "source": source.get("metadata", {}).get("source_url", "Unknown"),
                "content": source.get("content", "")[:100] + "...",
                "relevance": source.get("relevance", 0.5)
            })
        
        return citations