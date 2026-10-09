"""
Permitted knowledge graph schema (SDD 4.4, Figure 7). The team will refine these types as the project progresses.
Node types: Gene, Protein, Disease, Drug
    each node has entity_id, name, and chunk_ids (the chunks that mention it)
Relationship types, as (source, type, target):
    (Gene, ENCODES, Protein)
    (Gene, ASSOCIATED_WITH, Disease)
    (Protein, ASSOCIATED_WITH, Disease)
    (Drug, TARGETS, Protein)
    (Drug, TREATS, Disease)
    (Drug, STUDIED_FOR, Disease)
    each relationship keeps the chunk_ids that support it, which map to document and page (SDD 4.4)
Normalization: lowercase, trim, collapse whitespace, so repeated mentions reuse the same entity_id within the account's workspace (3.5.3)
Used by extraction (prompt and validation, 3.5.2), graph_store (constraints), and GET /api/graph/types (explorer filters, 3.9.1)
Keep the colors in frontend/src/components/GraphView.jsx in sync with the node types
"""
