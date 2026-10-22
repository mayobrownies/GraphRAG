"""
PDF text extraction and chunking
Input: PDF bytes + document id. Output: chunks, each with chunk id, document id, page number and text
Raise a clear error for empty, unreadable, encrypted or image-only PDFs so ingestion marks the document 'failed'
"""
from unstructured.partition.pdf import partition_pdf

def parse_pdf(pdf, doc_id):
    chunks = partition_pdf(
        filename=pdf,
        strategy="auto",
        chunking_strategy="by_page",
        max_characters=2000,
        new_after_n_chars=1500,
    )
    data = []
    for i, chunk in chunks:
            page_number = chunk.metadata.page_number if hasattr(chunk, "metadata") else Exception("Page number not found")
            data.append({
                "chunk_id": i,
                "document_id": doc_id,
                "page_number": page_number,
                "text": str(chunk)
            })
    return data


"""# test code
try:
    info = parse_pdf(INSERT PATH HERE, 0)
    # debug on this line and ensure that it works
    p = 1 + 1
except Exception as e:
    print(e)"""
