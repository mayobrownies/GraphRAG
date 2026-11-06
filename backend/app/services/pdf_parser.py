"""
PDF text extraction and chunking
Input: PDF bytes + document id. Output: chunks, each with chunk id, document id, page number and text
Raise a clear error for empty, unreadable, encrypted or image-only PDFs so ingestion marks the document 'failed'
"""
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError
from pypdf.errors import EmptyFileError

def parse_pdf(pdf_path, doc_id):
  try:
    reader = PdfReader(pdf_path)

    # Check if the PDF is encrypted
    if reader.is_encrypted:
        raise FileNotDecryptedError

    # Check if the PDF has no pages
    if not reader.pages:
      raise EmptyFileError

    chunks = []
    chunk_counter = 0

    for page_num, page in enumerate(reader.pages, start=1):
      text = page.extract_text()
      if not text:
        continue  # Skip pages with no extractable text

      max_characters=2000
      # Simple sliding/character-based chunking to approximate max_characters
      for i in range(0, len(text), max_characters):
        chunk_text = text[i : i + max_characters]
        chunk = {
            "chunk_id": f"{doc_id}_chunk_{chunk_counter:03d}",
            "document_id": doc_id,
            "page_number": page_num,
            "text": chunk_text,
        }
        chunks.append(chunk)
        chunk_counter += 1

    # If no text was extracted across any page (e.g., image-only PDF)
    if not chunks:
      raise EmptyFileError

    return chunks
  except FileNotDecryptedError:
    raise Exception("PDF file is encrypted")
  except EmptyFileError:
    raise Exception("PDF file is empty.")
  except Exception:
    raise Exception("The PDF unreadable.")

