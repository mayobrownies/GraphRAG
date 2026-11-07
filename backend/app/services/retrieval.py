"""
GraphRAG: embed the query -> vector_store search over the group's ready docs -> the papers those chunks came from
-> graph_store.neighbors for their strongest ASSOCIATED_WITH links -> merge the results, remove duplicates,
keep the paper path that was used
Standard RAG (benchmark baseline): vector search only, with the same documents and settings
Results are limited to the 'ready' papers of one of the user's groups (document_db.ready_ids on the group's document_ids)
"""