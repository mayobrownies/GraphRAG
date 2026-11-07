# KG RAG Engine

A GraphRAG engine for research papers (PDFs). Each paper is one `Paper` node in a Neo4j graph. Papers are linked by undirected `ASSOCIATED_WITH` edges, weighted by the cosine similarity of their paper-level embeddings. Chunk embeddings go in Qdrant, the original PDFs in Supabase Storage, and document metadata, processing state and groups in Supabase Postgres.

Each user has a **library** of the PDFs they uploaded, and **groups** of library papers (for example, one group for medical research and one for AI research). Users create, rename and delete groups in the Graph Explorer, and tick library papers to put them in a group. The Graph Explorer shows the active group's paper graph, and questions are answered from the active group's papers, citing the source document and page.

Models run on Ollama: `qwen3.5:0.8b` for chat and `qwen3-embedding:0.6b` for embeddings.

The SRS and SDD are in `docs/`. Where they disagree with the code (for example, the SDD's entity/relationship graph and its shared global corpus), this README follows the code.

## Status

| Area | State |
| --- | --- |
| Auth (`core/auth.py`) | Done. Verifies Supabase access tokens (ES256/RS256, audience `authenticated`) against `SUPABASE_JWKS_URL`. |
| Library and groups (`repositories/document_db.py`) | Done. Owner-only reads, keyset pagination, duplicate detection by sha256, status updates, groups and membership, profiles and usernames. |
| PDF storage (`repositories/document_store.py`) | Done. Upload, replace, download, delete, signed URLs. |
| Paper graph (`graph_schema.py`, `repositories/graph_store.py`) | Done. Unit tests in `test_graph_store.py`. Live Neo4j tests in `test_graph_store_integration.py` run in CI (`neo4j.yml`) and are skipped locally unless `NEO4J_TEST_*` is set. |
| Chunk vectors (`repositories/vector_store.py`) | Done. Collection setup, insert, search filtered by doc ids, delete by doc id. |
| Ollama client (`models.py`) | Done. `chat` and `embed`. |
| `GET /api/documents`, `GET /api/documents/{id}`, `GET /api/documents/{id}/download` | Done. |
| `/api/groups` (`routers/groups.py`) | Done. See [Groups](#groups). |
| `POST /api/documents`, `POST .../retry`, `PUT .../{id}`, `DELETE .../{id}` | Return `501`. Each handler lists its planned steps in comments. They wait on `services/jobs.py`. |
| `routers/account.py`, `routers/query.py` | Docstrings only. Not registered in `main.py`. |
| `services/` (ingestion, jobs, pdf_parser, extraction, retrieval, generation) | Docstrings only. |
| Startup (`main.py`) | Connects Supabase and Neo4j (and creates the Neo4j constraints), then marks stuck `processing` documents as `failed`. Qdrant and Ollama are not wired yet. |
| Frontend | Built against the current API: library (Workspace tab), groups and the paper graph (Graph Explorer tab), questions and benchmarks over the active group. Tests run against mocked API responses. `/api/me`, `/api/query` and `/api/benchmark` don't exist yet, so the username, Ask and Compare calls fail until they land. |

## Groups

- Every user has at least one group. `GET /api/groups` creates an empty "Group 1" when the user has none, including after they delete their last group.
- Group names are trimmed, 1 to 100 characters, and unique per user (409 otherwise).
- A library paper can be in any number of groups. Any paper can be added, but only `ready` papers appear in the graph and in answers.
- Removing a paper from a group keeps it in the library. Deleting a group keeps its papers. Deleting a paper from the library removes it from every group.
- A user can only see or change their own groups and papers; anything else is a 404.

| Endpoint | Does |
| --- | --- |
| `GET /api/groups` | The user's groups, oldest first, each with `document_ids` |
| `POST /api/groups` `{name}` | Create a group (201) |
| `PATCH /api/groups/{id}` `{name}` | Rename |
| `DELETE /api/groups/{id}` | Delete (204) |
| `PUT /api/groups/{id}/documents/{doc_id}` | Add a library paper; adding twice is harmless |
| `DELETE /api/groups/{id}/documents/{doc_id}` | Remove a paper from the group |
| `GET /api/groups/{id}/graph?search=&limit=50&per_paper=5` | The group's `ready` papers and their strongest links: `{nodes: [{doc_id, name}], edges: [{source, target, weight}]}` |

## Paper graph

Defined in `backend/app/graph_schema.py` and `backend/app/repositories/graph_store.py`.

- `(:Paper {doc_id, account, name, search_name, embedding, revision, active})`, one node per document. `doc_id` is unique, enforced by a constraint.
- `(:Paper)-[:ASSOCIATED_WITH {weight}]->(:Paper)`: `weight` is the plain cosine similarity, in [-1, 1]. An edge is stored only if `weight >= MIN_WEIGHT` (0.3). Edges are written in one direction but always read as undirected.
- `begin_document(account, doc_id)` starts a new revision. It clears the old embedding and edges and returns the revision number.
- `add_paper(account, revision, paper)` stores the embedding and links the paper to every other active paper of the same account. It raises `StaleGraphWrite` if the revision has been replaced or deleted in the meantime, so an old job can't write.
- `delete_document` leaves a tombstone (`active=false`), so a late job can't bring the paper back.
- Each account's writes take that account's `PaperGraphLock` node, so papers added at the same time still get linked to each other.
- `graph(doc_ids, text, limit, per_paper)` returns the selected papers whose name contains `text`, plus each paper's `per_paper` strongest edges among them. `neighbors(doc_ids, seed_ids, per_paper)` returns each seed's strongest links. Reads trust the `doc_ids` they are given, so callers must pass only ids that are authorized and `ready` (`document_db.ready_ids`).

Groups live only in Postgres. The graph doesn't know about them: a group's graph is `graph()` over the group's ready papers.

Qdrant chunk payloads hold `doc_id, chunk_id, page, account, text`. Search always filters by `doc_id`.

## Data model (Supabase)

`supabase/schema.sql` can be run more than once. It creates:

- `profiles`: one row per account, with an optional unique username of 3 to 30 characters.
- `documents`: the library. `owner_id`, `name`, `sha256`, `storage_path`, `status` (`processing`, `ready` or `failed`), `stage`, `error`, and timestamps. The pair `(owner_id, sha256)` is unique.
- `groups`: `owner_id`, `name`, timestamps. The pair `(owner_id, name)` is unique.
- `group_documents`: `(group_id, document_id, owner_id, added_at)`. Composite foreign keys on `(id, owner_id)` to both tables mean a group can only hold its owner's papers. Deleting a paper or a group cascades here.
- Row level security on every table. The backend uses the secret key, which bypasses RLS, so `DocumentDB` filters every query by owner itself.

PDFs are stored at `{owner_id}/{doc_id}.pdf` in a private bucket.

Databases created before groups still have the global corpus. Rerunning `schema.sql` migrates them: it deletes global documents, drops `is_global` and `hidden_documents`, and adds the group tables. Delete the `global/` folder in the storage bucket by hand.

## Layout

    backend/    FastAPI app, tests, scripts
    frontend/   React 18 + Vite + Cytoscape UI; nginx in Docker, Netlify in deployment
    supabase/   schema.sql
    docs/       SRS and SDD (.docx)
    .github/    CI workflows and pull request template
    docker-compose.yaml, render.yaml, netlify.toml

The backend is layered as routers -> services -> repositories:

    backend/app/
      main.py          lifespan (Supabase clients, fail stuck jobs), CORS, router registration, /health
      models.py        Ollama client: chat and embed
      graph_schema.py  Paper input type, name normalization, MIN_WEIGHT
      core/            config (settings), auth (current_user), deps (repository dependencies), errors
      schemas/         API shapes: auth.User, documents (DocumentRecord, DocumentList, SignedUrl), groups (GroupRecord, PaperGraph)
      routers/         documents (partly done), groups, account and query (stubs)
      services/        ingestion pipeline, jobs, PDF parsing, extraction, retrieval, generation (stubs)
      repositories/    graph_store (Neo4j), vector_store (Qdrant), document_store (Supabase Storage), document_db (Supabase Postgres)
    backend/scripts/
      check_neo4j.py   connectivity check; --init-schema creates the constraints

Routers call services and never touch a datastore or the LLM directly. Each repository file covers one datastore.

## Configuration

Settings are read from the environment first, then from `ProjectCode/.env`, which is git-ignored (`backend/app/core/config.py`). Vite also reads the `VITE_*` keys from that file. There is no `.env.example`; ask the team lead for the shared values.

| Key | Used by |
| --- | --- |
| `APP_ENV`, `LOG_LEVEL`, `CORS_ORIGINS` (comma-separated) | backend |
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | backend; template in `backend/.env.neo4j.example` |
| `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` (default `graphrag_chunks`) | backend |
| `OLLAMA_BASE_URL`, `OLLAMA_LLM_MODEL`, `OLLAMA_EMBED_MODEL` | backend, `ollama-pull` |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_JWKS_URL`, `SUPABASE_STORAGE_BUCKET` | backend |
| `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` | frontend build |

The backend won't start without `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_STORAGE_BUCKET`, `NEO4J_URI`, `NEO4J_USERNAME` and `NEO4J_PASSWORD`.

Tuning values with defaults: `MAX_UPLOAD_MB=20`, `SIGNED_URL_EXPIRES_S=300`.

## Setup

1. Create a Supabase project. Run `supabase/schema.sql` in the SQL editor, then create a **private** storage bucket whose name matches `SUPABASE_STORAGE_BUCKET`.
2. Enable the Google provider under Authentication > Providers, and add `http://localhost:3000` to the redirect URLs.
3. Create `ProjectCode/.env` with the keys above.
4. Run `docker compose up --build`. This starts Neo4j, Qdrant, Ollama, the backend (port 8000) and the frontend (port 3000). On first run, `ollama-pull` downloads both models.
5. Open http://localhost:3000.

## Development and tests

    cd backend && pip install -r requirements-dev.txt && pytest       # unit tests; live Neo4j tests skip
    cd backend && uvicorn app.main:app --reload                       # API on localhost:8000
    cd backend && python -m scripts.check_neo4j [--init-schema]       # check the Neo4j credentials in .env
    cd frontend && npm install && npm run dev                         # UI on localhost:3000, proxies /api to :8000
    cd frontend && npm test && npm run lint                           # vitest, oxlint

To run the live Neo4j tests (`-m integration`), set `NEO4J_TEST_URI`, `NEO4J_TEST_USERNAME`, `NEO4J_TEST_PASSWORD` and, optionally, `NEO4J_TEST_DATABASE`. The tests tag their data with a random prefix and delete it afterwards.

## Workflow and CI

Work on a branch and open a pull request into `main` using the template.

- `.github/workflows/ci.yml` runs on every PR and on pushes to `main`: backend `pytest`, then frontend lint, tests and build.
- `.github/workflows/neo4j.yml` runs the graph tests against a `neo4j:5.26-community` service on PRs that touch `backend/`.

## Deployment

- Backend: Render (`render.yaml`), using Neo4j Aura and Qdrant Cloud. Secret keys are set in the Render dashboard.
- Frontend: Netlify (`netlify.toml`, Node 24). Set `VITE_API_URL` (the Render URL), `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. Add the Netlify URL to `CORS_ORIGINS` on Render and to the Supabase redirect URLs.

## Notes

- Chunks and queries must use the same embedding model (`OLLAMA_EMBED_MODEL`). `models.embed` uses `truncate=False`, so chunks must fit within the model's context.
- Secret keys live only in backend environment variables. The browser sends a Supabase Bearer token, not cookies.
- API responses never include `owner_id`, `sha256` or `storage_path`.
