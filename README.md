# Medical GraphRAG

A GraphRAG pipeline for medical PDFs. Documents are chunked, an LLM (Qwen 3.5:0.8b through Ollama) extracts entities and relationships that are validated against a fixed schema, and the results are stored in a Neo4j Knowledge Graph and a Qdrant vector index. Queries use hybrid retrieval (vector search plus multi-hop Cypher traversal) and return grounded answers with page-level sources and the exact graph path.

Other documentation for this project is in `docs/`.

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
    frontend/   React (Vite) UI, served by nginx in Docker and by Netlify in deployment
    supabase/   schema.sql for Postgres tables and policies
    corpus/     base medical PDFs (git-ignored)
    docs/       project documentation
    .github/    CI workflow and pull request template
    docker-compose.yaml, .env.example, render.yaml, netlify.toml

### Backend layout

The backend is layered: routers -> services -> repositories.

    backend/app/
      main.py          app setup, startup checks, router registration, /health
      models.py        Ollama client for chat and embeddings
      schemas.py       shared Pydantic types (SDD 5.5)
      graph_schema.py  allowed node and relationship types (SDD 4.4)
      core/            config, error handling and logging, auth
      routers/         HTTP endpoints: documents, query, graph, account
      services/        business logic: ingestion pipeline, extraction, PDF parsing, jobs, retrieval, generation
      repositories/    datastore access: graph_store (Neo4j), vector_store (Qdrant), document_store (Supabase Storage), document_db (Supabase Postgres)

- `core/`: settings, error handling and logging, auth
- `routers/`: HTTP endpoints; call services, never databases or the LLM
- `services/`: business logic; ingestion and query pipelines
- `repositories/`: storage only, one file per datastore
- `tests/`: pytest suite
- `scripts/`: one-off tools such as corpus seeding


## Setup

1. Create a Supabase project. Run `supabase/schema.sql` in the SQL editor and create a **private** storage bucket. Its name must match `SUPABASE_STORAGE_BUCKET`.
2. In Supabase, enable the Google provider (Authentication > Providers) with the Google client id and secret, and add `http://localhost:3000` to the redirect URLs.
3. `cp .env.example .env` and fill it in. `.env` is git-ignored. Ask the team lead for the shared values.
4. `docker compose up --build`. This runs Neo4j, Qdrant and Ollama locally. The `ollama-pull` service downloads the models on first run.
5. Open http://localhost:3000.
6. Optional global corpus: put PDFs in `corpus/`, then run `docker compose exec backend python -m scripts.seed_corpus /srv/corpus`.

## Development and tests

    cd backend && pip install -r requirements-dev.txt && pytest
    cd backend && uvicorn app.main:app --reload                  # API on localhost:8000
    cd frontend && npm install && npm run dev                    # UI on localhost:3000, proxies /api to localhost:8000
    cd frontend && npm test && npm run lint

Neo4j storage now includes schema validation, stable entity IDs, source evidence, bounded graph traversal, and document cleanup. See [Neo4j backend notes](docs/neo4j-backend.md) for setup and interfaces; graph routes and ingestion integration are still in progress.

## Workflow

Work on a branch, open a pull request into `main`, and fill in the template. CI runs the backend tests and the frontend lint, tests and build on every pull request.

## Deployment

- Backend: Render (`render.yaml`), using Neo4j Aura and Qdrant Cloud. Secret keys are set in the Render dashboard.
- Frontend: Netlify (`netlify.toml`). Set `VITE_API_URL` (the Render URL), `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in the Netlify dashboard, and add the Netlify URL to `CORS_ORIGINS` on Render and to the Supabase redirect URLs.

## Notes

- The embedding model is `qwen3-embedding:0.6b`, set by `OLLAMA_EMBED_MODEL`. Chunks and queries must use the same model.
- Browser traffic is HTTPS and JSON in deployment.
- Secret keys live only in backend environment variables.
