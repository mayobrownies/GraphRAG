"""
Document upload and management tests (3.4, 3.8.3, 3.9.3)
Non-PDF and oversized uploads are rejected before indexing
A valid upload ends 'ready' and the list shows its name and state
Empty or image-only PDF ends 'failed' with a short message
Same file uploaded twice returns 409; override=true replaces and re-indexes it
Retry of a failed document reuses the same document id and leaves no duplicate index records
Delete removes the PDF, the Neo4j records, and the Qdrant vectors for that document
Removing a global document hides it for that user only
"""
