from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class DocumentOut(BaseModel):
    id: str
    filename: str
    file_size: int
    uploaded_at: datetime
    status: str
    title: Optional[str] = None
    author: Optional[str] = None
    processing_progress: Optional[int] = None
