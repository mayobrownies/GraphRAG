"""
Supabase Storage: the private bucket (SUPABASE_STORAGE_BUCKET) that holds the original PDFs
Upload, download, replace and delete PDFs, and create signed URLs to open a source PDF
Paths are {owner_id or "global"}/{doc_id}.pdf, so a retry or replace keeps the same path; store it in documents.storage_path
The documents table (metadata and processing state) lives in document_db.py; the SDD's "Document Store" covers both
"""

from dataclasses import dataclass

from supabase import AsyncClient

PDF_OPTIONS = {"content-type": "application/pdf"}


@dataclass
class DocumentStore:
    client: AsyncClient
    bucket: str

    @staticmethod
    def path_for(doc_id: str, owner_id: str | None) -> str:
        # owner_id None means a global corpus document
        return f"{owner_id or 'global'}/{doc_id}.pdf"

    async def upload(self, path: str, data: bytes) -> str:
        # Fails if a file already exists at this path; use replace to overwrite
        await self.client.storage.from_(self.bucket).upload(path, data, PDF_OPTIONS)
        return path

    async def download(self, path: str) -> bytes:
        return await self.client.storage.from_(self.bucket).download(path)

    async def signed_url(self, path: str, expires_in: int) -> str:
        # The bucket is private, so the UI opens PDFs through a short-lived signed URL
        response = await self.client.storage.from_(self.bucket).create_signed_url(path, expires_in)
        return response["signedURL"]

    async def replace(self, path: str, data: bytes) -> str:
        await self.client.storage.from_(self.bucket).upload(path, data, {**PDF_OPTIONS, "upsert": "true"})
        return path

    async def delete(self, path: str) -> bool:
        removed = await self.client.storage.from_(self.bucket).remove([path])
        return len(removed) > 0
