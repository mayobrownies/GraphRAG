"""
Authentication should be validated before any of these calls work
upload a PDF: check type and size, detect duplicates with an override option (3.4.6), start ingestion in the background, return DocumentRecord
list the user's documents plus the global corpus, with status
retry a failed document
replace a document's PDF, which re-indexes it
delete an own document, or remove a global document from the user's workspace
signed URL to open the source PDF
"""