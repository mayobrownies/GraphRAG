"""
Document ingestion pipeline
download PDF -> pdf_parser -> extraction (per chunk) -> graph_store write -> embed chunks (models.embed) -> vector_store write -> mark 'ready'
Update the status/progress message in document_store at each step
On error: mark 'failed' with a short message for the user, log the details, and remove any partial index records
One job per document at a time - if a document is deleted or replaced, its old job must not write to Neo4j or Qdrant (see jobs.py)
A retry reuses the same document id
"""