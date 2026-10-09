"""
Neo4j
Create constraints at startup, upsert entities and relationships with chunk ids, 
traverse 1–2 hops from seed entities, search, expand and node details for the explorer, 
and delete everything for a document id
Every query is limited to the allowed doc ids
"""