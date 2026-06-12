import asyncio
import logging
import math
import httpx
from typing import List, Dict, Any
from bson import ObjectId
from app.config import settings
from app.database import Database

logger = logging.getLogger("app.vector_service")

_local_embedder = None

def get_local_embedder():
    """
    Lazily initializes the fastembed model on first use.
    """
    global _local_embedder
    if _local_embedder is None:
        from fastembed import TextEmbedding
        # BAAI/bge-small-en-v1.5 has 384 dimensions and is extremely fast and accurate
        _local_embedder = TextEmbedding()
    return _local_embedder

async def get_embeddings(texts: List[str], is_query: bool = False) -> List[List[float]]:
    """
    Generates embeddings for a list of texts using the selected provider (Gemini, Local, or Ollama).
    """
    if not texts:
        return []

    if settings.EMBEDDING_PROVIDER == "ollama":
        try:
            embeddings = []
            async with httpx.AsyncClient() as client:
                for text in texts:
                    response = await client.post(
                        f"{settings.OLLAMA_BASE_URL}/api/embeddings",
                        json={
                            "model": settings.OLLAMA_EMBEDDING_MODEL,
                            "prompt": text
                        },
                        timeout=30.0
                    )
                    response.raise_for_status()
                    embeddings.append(response.json()["embedding"])
            return embeddings
        except Exception as e:
            logger.error(f"Ollama embedding generation failed: {e}")
            raise RuntimeError(f"Ollama embedding failed: {str(e)}")
            
    elif settings.EMBEDDING_PROVIDER == "local":
        try:
            embedder = get_local_embedder()
            # Offload CPU-heavy embedding calculation to a separate thread pool
            def run_local_embedding():
                embeddings_generator = embedder.embed(texts)
                return [e.tolist() for e in embeddings_generator]
            return await asyncio.to_thread(run_local_embedding)
        except Exception as e:
            logger.error(f"Local embedding generation failed: {e}")
            raise RuntimeError(f"Local embedding failed: {str(e)}")
            
    else:
        raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")


async def store_document_chunks(document_id: str, chunks: List[Dict[str, Any]], start_progress: int = 0) -> int:
    """
    Generates embeddings in batches of 100 and saves them in MongoDB.
    """
    if not chunks:
        return 0

    batch_size = 100
    total_stored = 0
    total_chunks = len(chunks)
    doc_obj_id = ObjectId(document_id)
    
    chunks_collection = Database.get_chunks_collection()
    documents_collection = Database.get_documents_collection()

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        
        # Build contextualized texts if context exists
        texts = []
        for chunk in batch:
            if chunk.get("context"):
                texts.append(f"{chunk['context']}\n\n{chunk['text']}")
            else:
                texts.append(chunk["text"])
        
        # Generate embeddings for this batch
        embeddings = await get_embeddings(texts, is_query=False)
        
        if len(embeddings) != len(batch):
            raise ValueError("Generated embeddings count does not match batch chunks count.")

        db_chunks = []
        for idx, chunk in enumerate(batch):
            db_chunks.append({
                "document_id": doc_obj_id,
                "text": chunk["text"],
                "context": chunk.get("context", ""),
                "embedding": embeddings[idx],
                "metadata": {
                    "page_number": chunk["metadata"]["page_number"],
                    "chunk_index": chunk["metadata"]["chunk_index"]
                }
            })
            
        await chunks_collection.insert_many(db_chunks)
        total_stored += len(db_chunks)
        
        # Calculate progress from the remaining percentage space
        if start_progress == 80:
            progress = 80 + int((total_stored / total_chunks) * 20)
        else:
            progress = int((total_stored / total_chunks) * 100)
            
        progress = min(progress, 99)
        
        await documents_collection.update_one(
            {"_id": doc_obj_id},
            {"$set": {"processing_progress": progress}}
        )
        
        logger.info(f"Stored batch {i // batch_size + 1}: {total_stored}/{total_chunks} chunks with context for document {document_id}.")

    return total_stored


def calculate_cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """
    Mathematical helper to compute cosine similarity between two vectors.
    Used as a fallback for local MongoDB setups.
    """
    dot_product = sum(a * b for a, b in zip(v1, v2))
    magnitude_v1 = math.sqrt(sum(a * a for a in v1))
    magnitude_v2 = math.sqrt(sum(b * b for b in v2))
    
    if not magnitude_v1 or not magnitude_v2:
        return 0.0
    return dot_product / (magnitude_v1 * magnitude_v2)


async def search_similar_chunks(query_text: str, limit: int = 4, document_id: str = None) -> List[Dict[str, Any]]:
    """
    Searches for text chunks mathematically similar to the query.
    Attempts MongoDB Atlas Vector Search first, and falls back to in-memory cosine similarity if needed.
    """
    # 1. Generate embedding for user query
    query_embeddings = await get_embeddings([query_text], is_query=True)
    if not query_embeddings:
        return []
    query_vector = query_embeddings[0]

    chunks_collection = Database.get_chunks_collection()
    
    # Check if MongoDB URI is an Atlas cloud instance (indicated by mongodb+srv://)
    is_atlas = settings.MONGODB_URI.startswith("mongodb+srv://")
    
    if is_atlas:
        try:
            # Setup vector search pipeline stage
            # The search index must be named "vector_index" in MongoDB Atlas
            vector_search_stage = {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": limit
            }
            
            # If document_id is provided, restrict search to that document only
            if document_id:
                vector_search_stage["filter"] = {
                    "document_id": ObjectId(document_id)
                }

            pipeline = [
                {"$vectorSearch": vector_search_stage},
                {
                    "$project": {
                        "document_id": 1,
                        "text": 1,
                        "context": 1,
                        "metadata": 1,
                        "score": {"$meta": "vectorSearchScore"}
                    }
                }
            ]
            
            # Run aggregation query
            results = []
            cursor = chunks_collection.aggregate(pipeline)
            async for doc in cursor:
                results.append({
                    "document_id": str(doc["document_id"]),
                    "text": doc["text"],
                    "context": doc.get("context", ""),
                    "page_number": doc["metadata"]["page_number"],
                    "score": doc.get("score", 1.0) # Fallback to 1.0 if score metadata is missing
                })
            
            if results:
                logger.info(f"Atlas Vector Search returned {len(results)} matches.")
                return results
                
        except Exception as atlas_err:
            logger.warning(f"MongoDB Atlas Vector Search query failed, falling back to local Python cosine similarity: {atlas_err}")
            # fall through to python similarity calculation

    # 2. Local fallback calculation (fetches all chunks for the document, computes similarity in Python)
    logger.info("Performing local in-memory cosine similarity search...")
    filter_query = {}
    if document_id:
        filter_query["document_id"] = ObjectId(document_id)

    # Fetch candidate documents
    candidates = []
    cursor = chunks_collection.find(filter_query, {"text": 1, "context": 1, "embedding": 1, "metadata": 1, "document_id": 1})
    async for doc in cursor:
        candidates.append(doc)

    if not candidates:
        return []

    # Calculate similarity scores
    scored_results = []
    for doc in candidates:
        similarity = calculate_cosine_similarity(query_vector, doc["embedding"])
        scored_results.append({
            "document_id": str(doc["document_id"]),
            "text": doc["text"],
            "context": doc.get("context", ""),
            "page_number": doc["metadata"]["page_number"],
            "score": similarity
        })

    # Sort results by similarity score descending and apply limit
    scored_results.sort(key=lambda x: x["score"], reverse=True)
    return scored_results[:limit]
