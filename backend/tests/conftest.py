"""
Shared test fixtures
TestClient on the real FastAPI app, with auth overridden to two test accounts (user A and user B) for isolation tests
In-memory fakes for document_store (Supabase), graph_store (Neo4j) and models (Ollama), so tests need no network
Qdrant runs for real in memory: QdrantClient(":memory:")
Fake LLM returns fixed JSON for extraction and a fixed answer for generation
Ingestion runs synchronously in tests so the document is 'ready' or 'failed' when the upload call returns
"""
