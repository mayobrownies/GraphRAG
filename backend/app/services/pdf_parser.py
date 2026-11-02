"""
PDF text extraction and chunking
Input: PDF bytes + document id. Output: chunks, each with chunk id, document id, page number and text
Raise a clear error for empty, unreadable, encrypted or image-only PDFs so ingestion marks the document 'failed'
"""
from unstructured.partition.pdf import partition_pdf
import traceback

def parse_pdf(pdf, doc_id):
    chunks = partition_pdf(
        filename=pdf,
        strategy="auto",
        chunking_strategy="by_title",
        max_characters=2000,
        new_after_n_chars=1500,
    )
    # check for issues here
    return chunks


""" test code
try:
    info = parse_pdf("", 0)
    # debug on this line and ensure that it works
    p = 1 + 1
except Exception:
    traceback.print_exc()
"""