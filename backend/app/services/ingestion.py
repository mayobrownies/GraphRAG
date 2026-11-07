"""
Document ingestion pipeline
download PDF -> pdf_parser -> embed chunks (models.embed) -> vector_store write
-> graph_store.begin_document, then add_paper with the paper's embedding (graph_schema.Paper) -> mark 'ready'
Update the status/progress message in document_db at each step
On error: mark 'failed' with a short message for the user, log the details, and remove any partial index records
One job per document at a time - if a document is deleted or replaced, its old job must not write to Neo4j or Qdrant (see jobs.py)
A retry reuses the same document id
"""