"""
Supabase Postgres and Storage
Insert, get and list documents (the user's own plus the global corpus), update status/stage/error
Find a duplicate by (owner, sha256) for the upload check
Upload, download and delete PDFs in the private bucket (SUPABASE_STORAGE_BUCKET), and create signed URLs to open a source PDF
Hide a global document from one user's workspace (hidden_documents) without affecting other accounts
The secret key bypasses RLS, so every query here must filter by owner and hidden_documents itself
"""
