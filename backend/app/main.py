"""
On startup: graph_store creates the Neo4j constraints, vector_store makes sure the Qdrant collection exists, 
and document_store marks any document stuck in 'processing' from a crash as 'failed' so the user can retry it
Set up logging and register the error handlers from errors.py
CORS: allow only the origins in config (CORS_ORIGINS)
Register the account, documents, query, and graph routers under the /api prefix (nginx forwards /api/ to the backend)
GET /health returns {"status": "ok"} for Render's health check (or which ever service we end up using)
"""