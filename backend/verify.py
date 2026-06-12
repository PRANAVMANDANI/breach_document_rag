import asyncio
import os
import sys
from datetime import datetime
from bson import ObjectId
from dotenv import load_dotenv

# Ensure we can import modules from the parent app folder
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from app.config import settings
from app.database import init_db, Database
from app.services.pdf_service import RecursiveTextSplitter
from app.services.vector_service import store_document_chunks, search_similar_chunks
from app.services.llm_service import generate_response_stream, generate_chunk_context, generate_document_summary

async def run_verification():
    print("==================================================")
    print("      RAG BACKEND INTEGRATION VERIFICATION")
    print("==================================================")
    
    # 1. Config Check
    print("\n[1/6] Reading Config Parameters...")
    print(f"      LLM Provider:      {settings.LLM_PROVIDER}")
    print(f"      Embedding Provider:{settings.EMBEDDING_PROVIDER}")
    print(f"      Target Database:   {settings.DB_NAME}")
    print(f"      MongoDB Server:    {settings.MONGODB_URI.split('@')[-1] if '@' in settings.MONGODB_URI else settings.MONGODB_URI}")
    
    # Check Groq API Key
    has_groq = bool(settings.GROQ_API_KEY)
    if settings.LLM_PROVIDER == "groq":
        print(f"      Groq API Key:      {'Set (Active)' if has_groq else 'Missing (Incomplete)'}")
        if not has_groq:
            print("\n[WARNING] GROQ_API_KEY is not defined in backend/.env.")
            print("          Groq LLM text generation will fail until a key is added.")
            print("          Get a key here: https://console.groq.com/")
            
    # 2. Database Connection Check
    print("\n[2/6] Validating MongoDB Connection...")
    try:
        await init_db()
        print("      -> Success: Connected to MongoDB database and indexes initialized.")
    except Exception as e:
        print(f"      -> ERROR: Could not connect to MongoDB: {e}")
        print("         Please check if your local MongoDB server is running or if Atlas URI is correct.")
        return

    # 3. Check text splitter chunking logic
    print("\n[3/6] Testing Recursive Character Text Splitter...")
    dummy_text = (
        "Retrieval-Augmented Generation (RAG) is an AI framework that grounds LLM models on external facts. "
        "To make this work, we break documents into smaller snippets called chunks. "
        "We also add a chunk overlap to preserve context across splits. "
        "This recursive character splitter splits text by paragraphs, then sentences, and finally words."
    )
    # Using small chunk sizes to force splits for testing
    splitter = RecursiveTextSplitter(chunk_size=120, chunk_overlap=30)
    chunks = splitter.split_text(dummy_text)
    print(f"      -> Split dummy text into {len(chunks)} chunks.")
    for i, chunk in enumerate(chunks):
        print(f"         Chunk {i+1} ({len(chunk)} chars): '{chunk}'")

    # 4. Check embedding generation & db insertion
    missing_llm_key = (settings.LLM_PROVIDER == "groq" and not has_groq)
    
    if missing_llm_key:
        print("\n[INFO] Skipping API-dependent checks (Embeddings/Generation) because required Groq API key is not set.")
        await Database.disconnect()
        print("\n==================================================")
        return

    print("\n[4/6] Testing Vector Embeddings & MongoDB Storage...")
    try:
        # Create a mock document in db
        documents_collection = Database.get_documents_collection()
        doc_res = await documents_collection.insert_one({
            "filename": "verification_test_file.pdf",
            "file_size": 4096,
            "status": "processing",
            "uploaded_at": datetime.utcnow()
        })
        doc_id = str(doc_res.inserted_id)
        
        # Test chunks
        test_chunks = [
            {"text": "FastAPI is a fast, asynchronous Python web framework built on Starlette and Pydantic.", "metadata": {"page_number": 1, "chunk_index": 0}},
            {"text": "MongoDB Atlas Vector Search allows unified storing of operations data and embeddings.", "metadata": {"page_number": 2, "chunk_index": 0}}
        ]
        
        # Test Context generation for these chunks
        print(f"      -> Generating chunk contexts via {settings.LLM_PROVIDER}...")
        whole_doc_test = "This document describes the modern web development stack. FastAPI is used for building backend APIs, while MongoDB Atlas provides data storage and vector search."
        doc_summary = await generate_document_summary(whole_doc_test)
        for chunk in test_chunks:
            chunk["context"] = await generate_chunk_context(doc_summary, chunk["text"])
            print(f"         Context generated: '{chunk['context']}'")
        
        stored_count = await store_document_chunks(doc_id, test_chunks)
        print(f"      -> Success: Embedded and stored {stored_count} chunks under Document ID: {doc_id}")

        # 5. Check semantic search retrieval
        print("\n[5/6] Testing Vector Search (Similarity Query)...")
        query_str = "What is the database vector search capability?"
        retrieved = await search_similar_chunks(query_str, limit=2, document_id=doc_id)
        print(f"      -> Search Query: '{query_str}'")
        print(f"      -> Retrieved {len(retrieved)} matches:")
        for idx, match in enumerate(retrieved):
            print(f"         Match {idx+1} (Similarity Score: {match['score']:.4f}, Page: {match['page_number']}):")
            print(f"           '{match['text']}'")

        # 6. Check LLM generation stream
        print("\n[6/6] Testing LLM Response Streaming...")
        print("      -> Generating response with context...")
        print("      --------------------------------------------------")
        sys.stdout.write("      ")
        sys.stdout.flush()
        async for word in generate_response_stream(query_str, retrieved):
            sys.stdout.write(word)
            sys.stdout.flush()
        print("\n      --------------------------------------------------")

        # Clean up database test records
        await documents_collection.delete_one({"_id": ObjectId(doc_id)})
        chunks_collection = Database.get_chunks_collection()
        await chunks_collection.delete_many({"document_id": ObjectId(doc_id)})
        print("      -> Cleaned up test records from MongoDB.")

    except Exception as api_err:
        print(f"      -> ERROR: Embedding / LLM API call failed: {api_err}")
        print("         Please verify your API key and internet connectivity.")

    await Database.disconnect()
    print("\n==================================================")
    print("      VERIFICATION SEQUENCE COMPLETED")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_verification())
