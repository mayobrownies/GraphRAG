"""
GraphRAG: embed the query -> vector_store search over the selected ready docs -> seed entities
-> graph_store 1-2 hop traversal -> merge the results, remove duplicates, keep the graph paths
Standard RAG (benchmark baseline): vector search only, with the same documents and settings
Results are limited to the user's documents plus the global corpus
"""