import hashlib
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from .. import repo
from ..auth import User, current_user
from ..config import get_settings
from ..services import pipeline
from ..stores import supabase

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _own_doc(user: User, doc_id: str) -> dict:
    doc = repo.get_doc(doc_id)
    if not doc or doc["is_global"] or doc["owner_id"] != user.id:
        raise HTTPException(404, "Document not found")
    return doc


def _remove(doc: dict) -> None:
    pipeline.remove_indexes(doc["id"])
    try:
        supabase().storage.from_(repo.bucket()).remove([doc["storage_path"]])
    except Exception:
        pass
    repo.delete(doc["id"])


@router.get("")
def list_documents(user: User = Depends(current_user)):
    return [{k: d.get(k) for k in ("id", "name", "status", "stage", "error", "is_global", "created_at")}
            for d in repo.list_docs(user.id)]


@router.post("", status_code=202)
async def upload(background: BackgroundTasks, file: UploadFile = File(...), override: bool = False,
                 user: User = Depends(current_user)):
    s = get_settings()
    name = file.filename or "document.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted.")
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds the {s.max_upload_mb} MB limit.")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(400, "The file is not a valid PDF.")
    sha = hashlib.sha256(data).hexdigest()
    dup = repo.find_by_hash(user.id, sha)
    if dup and not override:
        raise HTTPException(409, {"message": "This document was already uploaded. The existing copy was kept.",
                                  "existing_id": dup["id"]})
    if dup:
        _remove(dup)  # user chose to override: re-index from scratch
    doc_id = str(uuid.uuid4())
    path = f"{user.id}/{doc_id}.pdf"
    supabase().storage.from_(repo.bucket()).upload(path, data, {"content-type": "application/pdf"})
    repo.insert({"id": doc_id, "owner_id": user.id, "is_global": False, "name": name, "sha256": sha,
                 "storage_path": path, "status": "processing", "stage": "Queued"})
    background.add_task(pipeline.process_document, doc_id)
    return {"id": doc_id, "status": "processing"}


@router.post("/{doc_id}/retry", status_code=202)
def retry(doc_id: str, background: BackgroundTasks, user: User = Depends(current_user)):
    doc = _own_doc(user, doc_id)
    if doc["status"] != "failed":
        raise HTTPException(409, "Only failed documents can be retried.")
    repo.update(doc_id, status="processing", stage="Queued", error=None)
    background.add_task(pipeline.process_document, doc_id)
    return {"id": doc_id, "status": "processing"}


@router.delete("/{doc_id}", status_code=204)
def remove(doc_id: str, user: User = Depends(current_user)):
    _remove(_own_doc(user, doc_id))


@router.get("/{doc_id}/url")
def source_url(doc_id: str, user: User = Depends(current_user)):
    doc = repo.get_doc(doc_id)
    if not doc or not (doc["is_global"] or doc["owner_id"] == user.id):
        raise HTTPException(404, "Document not found")
    res = supabase().storage.from_(repo.bucket()).create_signed_url(doc["storage_path"], 3600)
    return {"url": res.get("signedURL") or res.get("signedUrl")}


profile_router = APIRouter(prefix="/api/me", tags=["account"])


@profile_router.get("")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "username": repo.get_username(user.id)}


@profile_router.put("/username")
def set_username(body: dict, user: User = Depends(current_user)):
    username = str(body.get("username", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username):
        raise HTTPException(400, "Username must be 3 to 30 characters: letters, digits, dot, dash, underscore.")
    try:
        repo.set_username(user.id, username)
    except Exception:
        raise HTTPException(409, "That username is taken.")
    return {"username": username}
