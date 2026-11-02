"""
PDF text extraction and chunking
Input: PDF bytes + document id. Output: chunks, each with chunk id, document id, page number and text
Raise a clear error for empty, unreadable, encrypted or image-only PDFs so ingestion marks the document 'failed'
"""
from unstructured.partition.pdf import partition_pdf

def parse_pdf(pdf, doc_id):
    try:
        elements = partition_pdf(
            filename=pdf,
            strategy="hi_res",
            chunking_strategy="by_title",
            max_characters=2000,
            new_after_n_chars=1500,
        )

        # for empty PDFs. If the PDF is unreadable or encrypted, partition_pdf will throw an error automatically
        if not elements:  # AKA if chunks == []
            raise Exception

        chunks = []
        for i, element in enumerate(elements):
            chunk = {
                "chunk_id": f"{doc_id}_chunk_{i:03d}",
                "document_id": doc_id,
                "page_number": element.metadata.page_number,
                "text": str(element)
            }
            chunks.append(chunk)

        return chunks
    except Exception:
        # Note: It will raise this error regardless of what issue the parsing runs into.
        raise Exception("The PDF is empty, unreadable, encrypted or image-only.")


