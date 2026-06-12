import asyncio
import logging
import os
from datetime import datetime
from typing import List
from bson import ObjectId
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse
from app.database import Database
from app.config import settings
from app.schemas.document import DocumentOut
from app.services.pdf_service import extract_pages_from_pdf, chunk_pdf_document, extract_metadata_from_pdf
from app.services.llm_service import extract_metadata_from_text, generate_chunk_context, generate_document_summary
from app.services.vector_service import store_document_chunks

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

logger = logging.getLogger("app.routes.document")
router = APIRouter(prefix="/documents", tags=["documents"])

async def process_pdf_background(
    document_id: str, 
    file_bytes: bytes, 
    current_title: str = None, 
    current_author: str = None,
    generate_context: bool = False
):
    """
    Background worker that extracts text, splits it into chunks, 
    generates embeddings, and stores them in MongoDB.
    Refines title/author metadata via LLM if missing.
    """
    try:
        documents_collection = Database.get_documents_collection()
        
        # 1. Parse PDF and extract page-by-page text
        pages_data = extract_pages_from_pdf(file_bytes)
        
        title = current_title
        author = current_author
        
        # Fallback to LLM to extract title/author from first page text if missing
        if pages_data and (not title or not author):
            first_page_text = pages_data[0]["text"]
            llm_meta = await extract_metadata_from_text(first_page_text)
            if llm_meta:
                if not title and llm_meta.get("title"):
                    title = llm_meta["title"]
                if not author and llm_meta.get("author"):
                    author = llm_meta["author"]
        
        # 2. Split pages into overlapping text chunks
        chunks = chunk_pdf_document(pages_data)
        
        # 2b. Generate situational contexts for chunks if enabled
        if chunks and generate_context:
            logger.info(f"Generating situational context for {len(chunks)} chunks using {settings.LLM_PROVIDER}...")
            whole_document = "\n".join([page["text"] for page in pages_data])
            
            # Generate summary first to stay under TPM rate limits
            logger.info("Generating overall document summary...")
            doc_summary = await generate_document_summary(whole_document)
            logger.info(f"Summary generated: '{doc_summary}'")
            
            semaphore = asyncio.Semaphore(5)
            rate_limit_tripped = False
            processed_contexts_count = 0
            total_chunks = len(chunks)
            last_progress = 0
            
            async def get_context_with_sem(chunk_text: str) -> str:
                nonlocal rate_limit_tripped, processed_contexts_count, last_progress
                async with semaphore:
                    if rate_limit_tripped:
                        return ""
                    try:
                        context = await generate_chunk_context(doc_summary, chunk_text)
                        processed_contexts_count += 1
                        progress = int((processed_contexts_count / total_chunks) * 80)
                        if progress > last_progress:
                            last_progress = progress
                            await documents_collection.update_one(
                                {"_id": ObjectId(document_id)},
                                {"$set": {"processing_progress": progress}}
                            )
                        return context
                    except Exception as e:
                        if "429" in str(e) or "quota" in str(e).lower() or "limit" in str(e).lower():
                            rate_limit_tripped = True
                            logger.warning("Rate limit tripped during chunk context generation. Aborting remaining requests.")
                        processed_contexts_count += 1
                        progress = int((processed_contexts_count / total_chunks) * 80)
                        if progress > last_progress:
                            last_progress = progress
                            await documents_collection.update_one(
                                {"_id": ObjectId(document_id)},
                                {"$set": {"processing_progress": progress}}
                            )
                        return ""
                    
            tasks = [get_context_with_sem(c["text"]) for c in chunks]
            contexts = await asyncio.gather(*tasks)
            for idx, ctx in enumerate(contexts):
                chunks[idx]["context"] = ctx
            logger.info("Context generation completed.")
        else:
            logger.info("Situational chunk context generation is disabled.")
        
        # 3. Generate embeddings and save chunks in MongoDB
        await store_document_chunks(document_id, chunks, start_progress=80 if generate_context else 0)
        
        # 4. Mark document status as processed and update metadata
        await documents_collection.update_one(
            {"_id": ObjectId(document_id)},
            {"$set": {
                "status": "processed",
                "processing_progress": 100,
                "title": title,
                "author": author
            }}
        )
        logger.info(f"Background processing completed successfully for document {document_id}")
    except Exception as e:
        logger.error(f"Failed to process document {document_id} in background: {e}")
        documents_collection = Database.get_documents_collection()
        await documents_collection.update_one(
            {"_id": ObjectId(document_id)},
            {"$set": {
                "status": "error",
                "processing_progress": 0,
                "error_message": str(e)
            }}
        )


@router.post("/", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...),
    generate_context: bool = settings.GENERATE_SITUATIONAL_CONTEXT
):
    """
    Uploads a PDF document and starts an asynchronous background processing task.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only PDF files are supported."
        )

    try:
        # Read file bytes in memory
        file_bytes = await file.read()
        file_size = len(file_bytes)
        
        # Synchronously extract initial PDF metadata
        pdf_meta = extract_metadata_from_pdf(file_bytes)
        title = pdf_meta.get("title")
        author = pdf_meta.get("author")
        
        # Insert initial metadata in MongoDB with 'processing' status
        doc_data = {
            "filename": file.filename,
            "file_size": file_size,
            "status": "processing",
            "uploaded_at": datetime.utcnow(),
            "title": title,
            "author": author,
            "processing_progress": 0
        }
        
        documents_collection = Database.get_documents_collection()
        insert_result = await documents_collection.insert_one(doc_data)
        doc_id = str(insert_result.inserted_id)

        # Save raw PDF file to local uploads directory
        file_path = os.path.join(UPLOAD_DIR, f"{doc_id}.pdf")
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        # Delegate chunking, embedding generation, and metadata refinement to background task
        background_tasks.add_task(process_pdf_background, doc_id, file_bytes, title, author, generate_context)

        return DocumentOut(
            id=doc_id,
            filename=file.filename,
            file_size=file_size,
            uploaded_at=doc_data["uploaded_at"],
            status="processing",
            processing_progress=0,
            title=title,
            author=author
        )
    except Exception as e:
        logger.error(f"Error initiating upload: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.get("/", response_model=List[DocumentOut])
async def list_documents():
    """
    Retrieves all uploaded documents, sorted by upload date descending.
    """
    try:
        documents_collection = Database.get_documents_collection()
        cursor = documents_collection.find().sort("uploaded_at", -1)
        
        docs = []
        async for doc in cursor:
            docs.append(DocumentOut(
                id=str(doc["_id"]),
                filename=doc["filename"],
                file_size=doc["file_size"],
                uploaded_at=doc["uploaded_at"],
                status=doc["status"],
                processing_progress=doc.get("processing_progress", 0 if doc["status"] == "processing" else 100),
                title=doc.get("title"),
                author=doc.get("author")
            ))
        return docs
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch documents: {str(e)}"
        )


@router.delete("/{document_id}", status_code=status.HTTP_200_OK)
async def delete_document(document_id: str):
    """
    Deletes a document metadata and all its associated text chunk embeddings from MongoDB.
    """
    try:
        doc_obj_id = ObjectId(document_id)
        
        # 1. Delete document metadata
        documents_collection = Database.get_documents_collection()
        delete_doc_result = await documents_collection.delete_one({"_id": doc_obj_id})
        
        if delete_doc_result.deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found."
            )
            
        # 1b. Delete local PDF file if it exists
        file_path = os.path.join(UPLOAD_DIR, f"{document_id}.pdf")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Deleted local file: {file_path}")
            except Exception as file_err:
                logger.warning(f"Failed to delete local file {file_path}: {file_err}")
            
        # 2. Delete all associated vector chunks
        chunks_collection = Database.get_chunks_collection()
        delete_chunks_result = await chunks_collection.delete_many({"document_id": doc_obj_id})
        
        logger.info(f"Deleted document {document_id} and {delete_chunks_result.deleted_count} associated chunks.")
        return {"status": "success", "message": f"Successfully deleted document and its {delete_chunks_result.deleted_count} chunks."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document {document_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(e)}"
        )


@router.get("/{document_id}/pdf")
async def get_document_pdf(document_id: str):
    """
    Serves the raw PDF file from the local uploads directory.
    """
    file_path = os.path.join(UPLOAD_DIR, f"{document_id}.pdf")
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF file not found."
        )
    return FileResponse(file_path, media_type="application/pdf")
