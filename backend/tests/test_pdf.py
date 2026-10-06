import pytest

from app.services.pdf import IngestError, extract_chunks


def test_invalid_pdf_is_rejected():
    with pytest.raises(IngestError):
        extract_chunks(b"%PDF-not really", "doc-1")
