"""PDF text extraction and chunking with source and page location (req 3.4.3, 3.4.4)."""
import io
import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

MIN_TEXT_CHARS = 50


class IngestError(Exception):
    """Raised for documents that cannot be indexed; message is shown to the user."""


def extract_chunks(data: bytes, doc_id: str, chunk_size: int = 1000, overlap: int = 150) -> list[dict]:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(i + 1, (p.extract_text() or "")) for i, p in enumerate(reader.pages)]
    except Exception as exc:
        raise IngestError("The PDF could not be read. It may be corrupted or encrypted.") from exc
    if sum(len(t.strip()) for _, t in pages) < MIN_TEXT_CHARS:
        raise IngestError("The document is empty, has unreadable text, or is image-only.")
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    chunks: list[dict] = []
    for page_no, text in pages:
        for piece in splitter.split_text(text):
            if piece.strip():
                chunks.append({
                    "id": str(uuid.uuid4()),
                    "doc_id": doc_id,
                    "page": page_no,
                    "index": len(chunks),
                    "text": piece.strip(),
                })
    return chunks
