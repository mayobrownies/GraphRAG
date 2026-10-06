"""Qdrant vector store (req 3.5.4, 3.6.2). Every point links document, chunk, account and entities."""
from qdrant_client.models import (Distance, FieldCondition, Filter, MatchAny, PayloadSchemaType,
                                  PointStruct, VectorParams)

from ..config import get_settings
from ..stores import qdrant


def ensure_collection() -> None:
    s = get_settings()
    client = qdrant()
    existing = {c.name for c in client.get_collections().collections}
    if s.qdrant_collection not in existing:
        client.create_collection(s.qdrant_collection,
                                 vectors_config=VectorParams(size=s.embed_dim, distance=Distance.COSINE))
    for field in ("doc_id", "scope"):
        try:
            client.create_payload_index(s.qdrant_collection, field, PayloadSchemaType.KEYWORD)
        except Exception:  # index may already exist
            pass


def upsert(doc_name: str, scope: str, owner_id: str | None, chunks: list[dict],
           vectors: list[list[float]], entity_ids: dict[str, list[str]]) -> None:
    points = [
        PointStruct(id=c["id"], vector=v, payload={
            "chunk_id": c["id"], "doc_id": c["doc_id"], "doc_name": doc_name, "scope": scope,
            "owner_id": owner_id, "page": c["page"], "text": c["text"],
            "entity_ids": entity_ids.get(c["id"], []),
        }) for c, v in zip(chunks, vectors)
    ]
    for i in range(0, len(points), 64):
        qdrant().upsert(get_settings().qdrant_collection, points=points[i:i + 64])


def search(vector: list[float], doc_ids: list[str], scopes: list[str], k: int) -> list[dict]:
    flt = Filter(must=[
        FieldCondition(key="doc_id", match=MatchAny(any=doc_ids)),
        FieldCondition(key="scope", match=MatchAny(any=scopes)),
    ])
    res = qdrant().query_points(get_settings().qdrant_collection, query=vector,
                                query_filter=flt, limit=k, with_payload=True).points
    return [{**p.payload, "score": float(p.score)} for p in res]


def get_chunks(chunk_ids: list[str]) -> dict[str, dict]:
    if not chunk_ids:
        return {}
    pts = qdrant().retrieve(get_settings().qdrant_collection, ids=chunk_ids, with_payload=True)
    return {str(p.id): p.payload for p in pts}


def delete_document(doc_id: str) -> None:
    qdrant().delete(get_settings().qdrant_collection, points_selector=Filter(must=[
        FieldCondition(key="doc_id", match=MatchAny(any=[doc_id]))]))
