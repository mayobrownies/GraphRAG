"""
Document API shapes. owner_id, sha256 and storage_path are internal and never sent to the browser
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.repositories.document_db import DocumentStatus


class DocumentRecord(BaseModel):
    # Built straight from a DocumentRow: DocumentRecord.model_validate(row); unlisted columns are dropped
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    is_global: bool
    status: DocumentStatus
    # Progress message while processing, and a short user-facing message when failed
    stage: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class DocumentList(BaseModel):
    items: list[DocumentRecord]
    # Send back as ?cursor= for the next page; null on the last page
    next_cursor: str | None


class SignedUrl(BaseModel):
    url: str
    expires_in: int
