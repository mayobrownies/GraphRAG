"""
Index the global medical corpus so every account can query it
For each PDF in the folder: hash it and check document_db for a global document with the same sha256
already 'ready': skip it
'failed': retry it with the same document id
not found: upload it to storage under global/, insert a document row with owner_id = null and is_global = true
Run ingestion synchronously and print ready or failed for each file
Use document_store, document_db and ingestion, the same path as user uploads, so there is no separate indexing code
"""


