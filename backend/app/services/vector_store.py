"""
Qdrant
Create the collection with the embedding size from config, upsert chunk vectors with a payload 
(doc_id, chunk_id, page, account, entity_ids, text), search filtered by doc ids, and delete by doc id
"""