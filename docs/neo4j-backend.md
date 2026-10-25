# Neo4j backend implementation

The graph storage layer is implemented in `backend/app/graph_schema.py` and
`backend/app/repositories/graph_store.py`. The graph HTTP router, extraction, ingestion and hybrid retrieval remain
integration work. Authentication, configuration, Supabase document services and
document read/download routes are implemented in the current backend. The
current `/health` endpoint does not establish database readiness.

## Connection and setup

Use Python 3.12 as in CI and Docker. From the repository root:

```powershell
cd backend
python -m pip install -r requirements-dev.txt
# Add the values in backend/.env.neo4j.example to the root .env,
# or set the four NEO4J_* process environment variables.
python -m scripts.check_neo4j
python -m scripts.check_neo4j --init-schema
pytest -q
```

The URI, database name and instance ID are separate settings. Use the exact
username, database and password from the Aura instance credentials. The default
database is `neo4j`. The database driver uses instance credentials, not the
console account's email/password. `neo4j+s://` enables TLS for Aura. Docker Compose
already overrides the local URI, username and database for its Neo4j container.
Do not put credentials in committed files. The tracked example has placeholders.

## Graph model

* `KGEntity` nodes also carry one of `Gene`, `Protein`, `Disease`, or `Drug`.
* Entity IDs are UUIDv5 values derived from account, entity type and normalized
  name. Normalization uses Unicode NFKC, case folding and collapsed whitespace.
  It is exact normalized-name matching, not biomedical synonym resolution.
* `KGChunk` keeps account, doc_id, chunk_id, page, text and revision.
  `MENTIONS` connects each chunk to its entities. The unique internal chunk key
  includes account and document, so another document may reuse a chunk_id safely.
* Typed medical edges are `ENCODES`, `ASSOCIATED_WITH`, `TARGETS`, `STUDIED_FOR`,
  and `TREATS`. Source/target type combinations are validated before writing.
* Each edge represents evidence from one chunk and stores doc_id, chunk_id,
  page, account, chunk_key and a stable edge_id. The same fact may have parallel
  edges when different chunks support it. Reads preserve the supporting evidence.
* `KGDocument` holds the account/document revision and active flag. A deleted
  document retains a small tombstone to reject late writes from an older job.

The design diagram's entity `chunk_ids` lists are implemented through `KGChunk`
and `MENTIONS`. Read results return filtered source references. This avoids
maintaining duplicate source lists and exposing references from unselected docs.
Relationship evidence is explicit rather than inferred from entity co-occurrence.

## Storage API

1. Create a reusable `GraphStore` with `GraphStore.connect(...)` and call
   `verify_connection()` and `create_constraints()` during configured startup.
2. Start a job with `revision = await store.begin_document(account, doc_id)`.
   This clears the previous graph revision for this document. The coordinator
   must first remove it from the set of ready documents.
3. For each validated `GraphChunk`, call
   `entity_ids = await store.upsert_chunk(account, revision, chunk)`.
4. Pass those exact entity_ids into the corresponding Qdrant `ChunkVector`.
5. After all graph and vector writes succeed, mark the document ready in
   Supabase. On failure, keep it out of retrieval and clean both stores.
6. Call `delete_document(account, doc_id)` on deletion or failure cleanup. It
   removes only this account/document evidence and any newly orphaned entities.
   Shared entities and facts with remaining evidence survive.
7. Call `close()` during shutdown.

`upsert_chunk` replaces that chunk's extraction atomically. Repeating it does
not duplicate evidence. Graph document writes, replacement and deletion acquire
the same document lock. Superseded writes raise `StaleGraphWrite`.

## Query contract

* `search(account, doc_ids, text='', node_type=None, limit=50)` returns nodes
  with filtered document/chunk/page source references.
* `node_details(account, doc_ids, entity_id)` adds source text, or returns None
  when the node has no evidence in this scope.
* `traverse(account, doc_ids, entity_ids, hops=2, limit=50)` returns node/edge
  paths, preserving stored edge direction even when traversed backwards.
* `expand(account, doc_ids, entity_id, limit=50)` returns one-hop paths.

All reads require an account and document selection. Empty selections return no
data. Every traversed edge must belong to that account and a selected document;
paths cannot bridge through a hidden document. Queries are limited to one or two
hops, have a transaction timeout, and cap returned paths at 200. Source text is
resolved with node_details. Do not aggregate parallel evidence by dropping its
source references when building an answer.

FastAPI must derive account from a verified token and resolve authorized, ready
doc_ids using Supabase. Passing arbitrary client doc_ids into this repository is
not authorization. For a shared initial corpus, agree a per-account indexing or
explicit corpus authorization model before integration; cross-account reads are
not enabled by this repository.

## Verification

On 25 October 2026, the complete backend test suite passed **104 tests**, with
18 live Supabase tests skipped. This includes seven integration tests against a
temporary Neo4j Community 5.26.32 server, in addition to graph unit tests and the
existing backend tests. The Qdrant tests use its in-memory client, which emits
a warning that payload indexes have no effect in local mode.

Real database testing found and fixed an argument-name collision that prevented
chunk writes and graph searches. The integration checks now cover repeat
ingestion, sourced two-hop traversal, account/document filtering, hidden-document
bridge prevention, reverse traversal direction, shared-evidence deletion, stale
revisions, chunk replacement, transaction rollback and concurrent writes.
The connection-check script also connected and initialized the local schema.

A read-only TLS connection and `RETURN 1` query succeeded against the supplied
Aura instance using its supplied instance username and database. Cloud schema
creation and graph writes were not exercised; no cloud records were changed.
The prior DNS failure from 20 October no longer occurs.

Run the integration tests against a dedicated test instance by setting
NEO4J_TEST_URI, NEO4J_TEST_USERNAME, NEO4J_TEST_PASSWORD and NEO4J_TEST_DATABASE.
They create and clean UUID-namespaced synthetic records. The separate
`.github/workflows/neo4j.yml` runs these checks against a Neo4j 5.26 service on
pull requests. That workflow has been added but has not been run remotely here.

## Remaining integration

Wire authenticated graph endpoints, validated extraction, shared lifecycle
coordination, Qdrant search-to-entity traversal, Supabase readiness and failure
cleanup, and application startup/shutdown. Persist the graph revision with a job
if jobs survive process restart. Qdrant needs its own stale-job protection or a
coordinator that guarantees canceled jobs cannot write. The graph revision alone
does not make writes across Neo4j, Qdrant and Supabase atomic.
