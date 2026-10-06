from fastapi import APIRouter, Depends, HTTPException, Query

from .. import repo
from ..auth import User, current_user
from ..config import GLOBAL_SCOPE
from ..schema import NODE_TYPES
from ..services import graph_store, vector_store

router = APIRouter(prefix="/api/graph", tags=["graph"])


def _ctx(user: User, doc_ids: str):
    requested = [d for d in doc_ids.split(",") if d]
    docs = repo.accessible_ready(user.id, requested or None)
    return [d["id"] for d in docs], [user.id, GLOBAL_SCOPE]


@router.get("/types")
def types(user: User = Depends(current_user)):
    return NODE_TYPES


@router.get("")
def overview(doc_ids: str = "", search: str = "", types: str = "", limit: int = Query(80, le=300),
             user: User = Depends(current_user)):
    ids, scopes = _ctx(user, doc_ids)
    if not ids:
        return {"nodes": [], "edges": []}
    return graph_store.overview(scopes, ids, search.strip(), [t for t in types.split(",") if t in NODE_TYPES], limit)


@router.get("/expand/{node_id}")
def expand(node_id: str, doc_ids: str = "", user: User = Depends(current_user)):
    ids, scopes = _ctx(user, doc_ids)
    return graph_store.expand(node_id, scopes, ids)


@router.get("/node/{node_id}")
def node(node_id: str, doc_ids: str = "", user: User = Depends(current_user)):
    ids, _ = _ctx(user, doc_ids)
    info = graph_store.node_info(node_id)
    if not info:
        raise HTTPException(404, "Node not found")
    sources = graph_store.node_sources(node_id, ids)
    texts = vector_store.get_chunks([s["chunk_id"] for s in sources])
    for s in sources:
        s["snippet"] = (texts.get(s["chunk_id"], {}).get("text") or "")[:300]
    return {**info, "sources": sources}
