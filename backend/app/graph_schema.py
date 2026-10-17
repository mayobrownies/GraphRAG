"""
Permitted knowledge graph schema. The team will refine these types as the project progresses.
Node types: (add types here)
    each node has entity_id, name, and chunk_ids (the chunks that mention it)
Relationship types, 
    (add types here)
    each relationship keeps the chunk_ids that support it, which map to document and page
Normalization: lowercase, trim, collapse whitespace, so repeated mentions reuse the same entity_id within the account's workspace
"""
