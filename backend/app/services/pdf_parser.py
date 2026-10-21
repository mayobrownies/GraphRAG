"""
PDF text extraction and chunking
Input: PDF bytes + document id. Output: chunks, each with chunk id, document id, page number and text
Raise a clear error for empty, unreadable, encrypted or image-only PDFs so ingestion marks the document 'failed'
"""
from unstructured.partition.pdf import partition_pdf
from unstructured.chunking.basic import chunk_by_text

def parsePDF(pdf, doc_id):
	elements = partition_pdf(
    filename=pdf,
    strategy="auto" 
	)
	chunks = chunk_by_text(
    elements, 
    max_characters=500, 
    overlap=50
	)
	data = []
	for i, chunk in enumerate(chunks, start=1):
        # extract page number
        page_number = chunk.metadata.page_number if hasattr(chunk, "metadata") else raise Exception("Page number not found")
    
        data.append({
            "chunk_id": f"chunk_{i}",
            "document_id": doc_id,
            "page_number": page_number,
            "text": str(chunk)
        })
	return data