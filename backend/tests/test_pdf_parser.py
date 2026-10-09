"""
pdf_parser tests (3.4.3, 3.4.4)
valid.pdf: produces chunks, each with chunk id, document id, page number, and text
Chunks stay under the configured chunk size
empty.pdf, image_only.pdf, encrypted.pdf: raise the parser error that makes ingestion mark the document 'failed'
"""
