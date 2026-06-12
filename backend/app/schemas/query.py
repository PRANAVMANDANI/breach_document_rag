from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class QueryRequest(BaseModel):
    question: str
    document_id: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None

class SourceChunk(BaseModel):
    text: str
    page_number: int
    score: float

class QueryResponse(BaseModel):
    answer: str
    sources: List[SourceChunk]
