"""
Pydantic types: DocumentStatus, DocumentRecord, SourceReference, GraphPath,
Response (with support full/partial/none), plus the query, benchmark and profile request/response models
Split by domain: auth.py (User), documents.py, groups.py (groups and the paper graph); query types get their own module
These are the API's public shapes; repositories keep their own dataclasses and routes convert on the way out
"""
