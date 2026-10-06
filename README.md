# Medical GraphRAG

A GraphRAG pipeline for medical PDFs. Documents are chunked, an LLM (Qwen 3.5:0.8b through Ollama) extracts entities and relationships that are validated against a fixed schema, and the results are stored in a Neo4j Knowledge Graph and a Qdrant vector index. Queries use hybrid retrieval (vector search plus multi-hop Cypher traversal) and return grounded answers with page-level sources and the exact graph path.

## Features (from the requirements specification)

- Google sign-in with Supabase Auth, optional custom username, sign out, per-account data isolation
- PDF upload with format and size validation, duplicate detection with override, states `processing`, `ready`, `failed`, retry of failed jobs
- Schema-validated entity and relationship extraction, normalized and deduplicated in Neo4j
- Chunk embeddings in Qdrant linked to document, chunk, account and graph entities
- Hybrid retrieval, grounded answers, "no usable context" and "partial evidence" handling
- Incremental re-indexing on document replacement or removal
- Interactive 2D graph explorer: search, filter, expand nodes, inspect sources, open the PDF, highlight answer path
- Benchmarks tab: Standard RAG and GraphRAG side by side

## Layout

    backend/    FastAPI app, pipeline services, tests, corpus seeding script
    frontend/   React (Vite) UI served by nginx
    supabase/   schema.sql for Postgres tables and policies
    corpus/     base medical PDFs (git-ignored)
    docs/       Software Design Document
    docker-compose.yml, .env.example

## Setup

1. Create a Supabase project. Run `supabase/schema.sql` in the SQL editor and create a **private** storage bucket named `documents`.
2. In Supabase, enable the Google provider (Authentication > Providers) and add your site URL (`http://localhost:3000`) to the redirect URLs.
3. `cp .env.example .env` and fill in the Supabase keys and a Neo4j password.
4. `docker compose up --build`. The `ollama-pull` service downloads the models on first run.
5. Open http://localhost:3000.
6. Optional global corpus: put PDFs in `corpus/`, add `- ./corpus:/srv/corpus` under the `backend` service volumes, restart, then run `docker compose exec backend python -m scripts.seed_corpus /srv/corpus`.

## Development and tests

    cd backend && pip install -r requirements.txt && pytest      # 29 tests
    cd frontend && npm install && npm test                       # 6 component tests
    cd frontend && npm run dev                                   # proxies /api to localhost:8000

The backend suite runs the real FastAPI app and an in-memory Qdrant against in-memory stand-ins for Supabase, Neo4j and Ollama. It covers upload validation, failure and retry, duplicate override, hybrid and standard retrieval, no-context and partial-support answers, account isolation, deletion and re-indexing, and the graph explorer endpoints. Run the stack with Docker Compose for a live check against real services.

## Notes

- The specification does not name an embedding model. `nomic-embed-text` (768 dimensions) is the default and is configurable through `EMBED_MODEL` and `EMBED_DIM`.
- Browser traffic is HTTPS and JSON in deployment (requirement 5.3.1). Terminate TLS at a reverse proxy in front of the frontend container.
- Secrets live only in backend environment variables. The Supabase anon key in the frontend build is public by design.
