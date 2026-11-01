"""
Authentication should be validated before any of these calls work
upload a PDF: check type and size, detect duplicates with an override option (3.4.6), start ingestion in the background, return DocumentRecord
list the user's documents plus the global corpus, with status
retry a failed document
replace a document's PDF, which re-indexes it
delete an own document, or remove a global document from the user's workspace
signed URL to open the source PDF

Upload, retry and replace all end by handing the doc_id to ingestion; this router never writes to Qdrant or Neo4j
Delete is the only route that cleans the vector and graph stores
override: when the user already owns this PDF, re-index that same document instead of returning 409
A visible global copy is always a 409, since the user can already use it
Download returns a short-lived signed URL, so the browser fetches the PDF from Supabase Storage, not through the API
Each body lists its steps as comments and ends in a 501 until implemented; auth still runs first, so a missing token is 401
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.core.auth import current_user
from app.core.config import Settings, get_settings
from app.core.deps import get_document_db, get_document_store
from app.core.errors import InvalidCursor
from app.repositories.document_db import MAX_PAGE_SIZE, DocumentDB, DocumentRow, DocumentStatus, Scope
from app.repositories.document_store import DocumentStore
from app.schemas.auth import User
from app.schemas.documents import DocumentList, DocumentRecord, SignedUrl

router = APIRouter(prefix="/documents", tags=["documents"])

NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Missing, or not visible to this user"}}
BAD_FILE = {
    status.HTTP_413_CONTENT_TOO_LARGE: {"description": "Larger than MAX_UPLOAD_MB"},
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"description": "Not a PDF"},
}


def not_implemented() -> HTTPException:
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Not implemented")


async def find_visible(db: DocumentDB, doc_id: str, user: User, scope: Scope = Scope.ALL) -> DocumentRow:
    # One 404 for unknown, invalid, hidden and other users' ids, so nothing reveals that a document exists
    row = await db.get(doc_id, user.id, scope=scope)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return row


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_409_CONFLICT: {"description": "Duplicate PDF; detail holds the existing document"}, **BAD_FILE},
)
async def upload_document(
    file: UploadFile = File(...),
    override: bool = Form(False),
    user: User = Depends(current_user),
) -> DocumentRecord:
    # TODO: blocked on a jobs.py entry point to start ingestion for a doc_id
    # 1. Read the file; over settings.max_upload_bytes -> 413, not a PDF (content type and %PDF- header) -> 415
    # 2. sha256 of the bytes
    # 3. db.find_duplicate(sha256, user.id)
    #    - own copy, override: store.replace(dup.storage_path, data), db.update(dup.id, "processing", name=, sha256=),
    #      start ingestion for dup.id, return it (202)
    #    - own copy, no override, or a global copy -> 409 with the existing document
    # 4. New document: doc_id = uuid4, path = DocumentStore.path_for(doc_id, user.id), store.upload(path, data)
    # 5. db.create(doc_id, user.id, file.filename, sha256, path)
    #    DuplicateDocument (an upload raced past step 3) -> store.delete(path), 409
    # 6. Start ingestion for doc_id in the background; return the 'processing' record (202)
    #    The UI polls GET /documents/{id} for progress
    raise not_implemented()


@router.get("", responses={status.HTTP_400_BAD_REQUEST: {"description": "Invalid cursor"}})
async def list_documents(
    scope: Scope = Scope.ALL,
    status_filter: DocumentStatus | None = Query(None, alias="status"),
    search: str | None = None,
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    # next_cursor from the previous page; omit for the first page
    cursor: str | None = None,
    user: User = Depends(current_user),
    db: DocumentDB = Depends(get_document_db),
) -> DocumentList:
    # get_all applies the owner, global and hidden rules
    try:
        page = await db.get_all(user.id, scope=scope, status=status_filter, search=search, limit=limit, cursor=cursor)
    except InvalidCursor as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from error
    return DocumentList(items=[DocumentRecord.model_validate(row) for row in page.items], next_cursor=page.next_cursor)


@router.get("/{doc_id}", responses=NOT_FOUND)
async def get_document(
    doc_id: str,
    user: User = Depends(current_user),
    db: DocumentDB = Depends(get_document_db),
) -> DocumentRecord:
    return DocumentRecord.model_validate(await find_visible(db, doc_id, user))


@router.post(
    "/{doc_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    responses={**NOT_FOUND, status.HTTP_409_CONFLICT: {"description": "Document is not 'failed'"}},
)
async def retry_document(doc_id: str, user: User = Depends(current_user)) -> DocumentRecord:
    # TODO: blocked on a jobs.py entry point to start ingestion for a doc_id
    # 1. find_visible(db, doc_id, user, Scope.OWN) -> 404 otherwise, so global documents can't be retried
    # 2. Status not 'failed' -> 409 (a processing document already has a job; a ready one has nothing to retry)
    # 3. db.update(doc_id, "processing"), which clears the old stage and error
    # 4. Start ingestion for doc_id with the same doc_id and stored PDF; return the refreshed record (202)
    raise not_implemented()


@router.put(
    "/{doc_id}",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **NOT_FOUND,
        status.HTTP_409_CONFLICT: {"description": "Same PDF as another of the user's documents"},
        **BAD_FILE,
    },
)
async def replace_document(
    doc_id: str,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
) -> DocumentRecord:
    # TODO: blocked on jobs.py entry points to cancel the old job and start ingestion for a doc_id
    # 1. Read and check the file as in upload (413, 415); sha256 of the bytes
    # 2. find_visible(db, doc_id, user, Scope.OWN) -> 404 otherwise
    # 3. db.update(doc_id, "processing", name=file.filename, sha256=); DuplicateDocument -> 409
    #    Marking processing first keeps the document out of retrieval while it changes
    # 4. store.replace(row.storage_path, data); same doc_id and path
    # 5. Start ingestion for doc_id; it cancels any old job and clears the old vectors and graph revision
    #    Return the refreshed record (202)
    raise not_implemented()


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def delete_document(doc_id: str, user: User = Depends(current_user)) -> None:
    # TODO: blocked on jobs.py (cancel a running job) and graph_store.delete_document (not on this branch yet)
    #       Step 2 could ship alone, but the whole route lands together in one change
    # 1. find_visible(db, doc_id, user) -> 404 otherwise
    # 2. Global document: db.hide(user.id, doc_id) and stop; shared data is untouched
    # 3. Own document: cancel any running job for doc_id
    # 4. Remove its vectors (vector_store.delete(doc_id)) and graph evidence (graph_store.delete_document)
    #    Ownership was checked in step 1, so deleting by doc_id alone is safe here
    # 5. store.delete(row.storage_path), then db.delete(doc_id, user.id) last
    #    The row goes last so a failure part-way still leaves a document the user can delete again
    raise not_implemented()


@router.get("/{doc_id}/download", responses=NOT_FOUND)
async def download_document(
    doc_id: str,
    user: User = Depends(current_user),
    db: DocumentDB = Depends(get_document_db),
    store: DocumentStore = Depends(get_document_store),
    settings: Settings = Depends(get_settings),
) -> SignedUrl:
    # Any document the user can see, own or global
    row = await find_visible(db, doc_id, user)
    url = await store.signed_url(row.storage_path, settings.signed_url_expires_s)
    return SignedUrl(url=url, expires_in=settings.signed_url_expires_s)
