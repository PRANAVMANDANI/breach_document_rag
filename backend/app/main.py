import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db, Database
from app.routes import document, query

# Set up logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("app.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown lifecycle events.
    Initializes database connection and indexes, and closes connections cleanly.
    """
    logger.info("Initializing database and search indexes...")
    try:
        await init_db()
        logger.info("Database initialized successfully.")
        
        # Purge collections on startup if configured (for clean dev testing)
        if settings.CLEAR_DB_ON_STARTUP:
            logger.info("CLEAR_DB_ON_STARTUP is enabled. Purging collections...")
            await Database.get_documents_collection().delete_many({})
            await Database.get_chunks_collection().delete_many({})
            logger.info("Database collections purged successfully on startup.")
            
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}")
        
    yield
    
    logger.info("Shutting down database connections...")
    await Database.disconnect()
    logger.info("Application shutdown complete.")


app = FastAPI(
    title="RAG Document Q&A API",
    description="Production-grade Document Retrieval-Augmented Generation (RAG) API using FastAPI and MongoDB Atlas Vector Search.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(document.router, prefix="/api")
app.include_router(query.router, prefix="/api")

@app.get("/health", tags=["health"])
async def health_check():
    """
    Health check endpoint for container environments and cloud platforms.
    """
    return {
        "status": "healthy",
        "environment": settings.ENV,
        "llm_provider": settings.LLM_PROVIDER
    }
