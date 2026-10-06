"""Document metadata and processing state in Supabase Postgres (req 5.2.5)."""
from datetime import datetime, timezone

from .config import get_settings
from .stores import supabase

T = "documents"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_docs(user_id: str) -> list[dict]:
    res = (supabase().table(T).select("*")
           .or_(f"owner_id.eq.{user_id},is_global.eq.true")
           .order("created_at", desc=True).execute())
    return res.data or []


def get_doc(doc_id: str) -> dict | None:
    res = supabase().table(T).select("*").eq("id", doc_id).limit(1).execute()
    return res.data[0] if res.data else None


def insert(row: dict) -> None:
    supabase().table(T).insert(row).execute()


def update(doc_id: str, **fields) -> None:
    fields["updated_at"] = _now()
    supabase().table(T).update(fields).eq("id", doc_id).execute()


def delete(doc_id: str) -> None:
    supabase().table(T).delete().eq("id", doc_id).execute()


def find_by_hash(user_id: str, sha: str) -> dict | None:
    res = (supabase().table(T).select("*").eq("owner_id", user_id)
           .eq("sha256", sha).limit(1).execute())
    return res.data[0] if res.data else None


def accessible_ready(user_id: str, requested: list[str] | None) -> list[dict]:
    """Only ready documents owned by the user or in the global corpus (req 2.2, 4.1.4)."""
    docs = [d for d in list_docs(user_id) if d["status"] == "ready"]
    if requested:
        wanted = set(requested)
        docs = [d for d in docs if d["id"] in wanted]
    return docs


def mark_stale_processing() -> None:
    (supabase().table(T).update({
        "status": "failed",
        "stage": "Interrupted",
        "error": "Processing was interrupted by a restart. Use retry.",
        "updated_at": _now(),
    }).eq("status", "processing").execute())


def get_username(user_id: str) -> str | None:
    res = supabase().table("profiles").select("username").eq("id", user_id).limit(1).execute()
    return res.data[0]["username"] if res.data else None


def set_username(user_id: str, username: str) -> None:
    supabase().table("profiles").upsert({"id": user_id, "username": username, "updated_at": _now()}).execute()


def bucket() -> str:
    return get_settings().supabase_bucket
