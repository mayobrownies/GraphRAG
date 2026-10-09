"""
A per-document lock and cancel token
One ingestion job runs per document, and a job for a document that was deleted or replaced must not write to Neo4j or Qdrant
"""