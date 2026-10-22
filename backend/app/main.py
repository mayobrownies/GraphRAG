"""
On startup: graph_store creates the Neo4j constraints, vector_store makes sure the Qdrant collection exists,
and document_db marks any document stuck in 'processing' from a crash as 'failed' so the user can retry it
Set up logging and register the error handlers from errors.py
CORS: allow only the origins in config (CORS_ORIGINS)
Register the account, documents, query, and graph routers under the /api prefix (nginx forwards /api/ to the backend)
GET /health returns {"status": "ok"} for Render's health check (or which ever service we end up using)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from supabase import acreate_client

from app.core.config import get_settings
from app.repositories.document_db import DocumentDB
from app.repositories.document_store import DocumentStore
from app.routers import documents

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    missing = [
        name
        for name in ("supabase_url", "supabase_secret_key", "supabase_storage_bucket")
        if not getattr(settings, name)
    ]
    if missing:
        raise RuntimeError(f"Missing settings: {', '.join(name.upper() for name in missing)}")

    # The secret key bypasses RLS; DocumentDB._select enforces who can see what
    supabase = await acreate_client(settings.supabase_url, settings.supabase_secret_key)
    app.state.document_db = DocumentDB(supabase)
    app.state.document_store = DocumentStore(supabase, settings.supabase_storage_bucket)

    # Neo4j: create the client and graph_store constraints here (graph owner)
    # Qdrant: create the client and make sure the collection exists here (vector owner)

    # No job survives a restart, so anything still 'processing' has stopped
    stuck = await app.state.document_db.fail_stuck()
    if stuck:
        logger.warning("Marked %d interrupted document(s) as failed", stuck)

    yield

    await supabase.postgrest.aclose()


app = FastAPI(lifespan=lifespan)

# The frontend sends a Bearer token, not cookies, so credentials aren't needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(documents.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
