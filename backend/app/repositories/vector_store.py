"""
Qdrant
Create the collection with the embedding size passed in by the caller, upsert chunk vectors with a payload
(doc_id, chunk_id, page, account, entity_ids, text), search filtered by doc ids, and delete by doc id
Point ids are random UUIDs (Qdrant only accepts UUIDs or ints), so a retry must delete the doc id before inserting again
"""

from dataclasses import dataclass, field
from uuid import uuid4

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    UpdateStatus,
    VectorParams,
)


@dataclass
class ChunkVector:
    doc_id: str
    chunk_id: str
    account: str
    page: int
    text: str
    vector: list[float]
    entity_ids: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    id: str
    score: float
    doc_id: str
    chunk_id: str
    page: int
    text: str
    entity_ids: list[str]


@dataclass
class VectorStore:
    client: AsyncQdrantClient
    collection: str

    async def create_collection(self, vector_size: int) -> bool:
        if await self.client.collection_exists(self.collection):
            return False
        await self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        for key in ("doc_id", "account"):
            await self.client.create_payload_index(
                collection_name=self.collection,
                field_name=key,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        return True

    async def insert(self, chunks: list[ChunkVector]) -> list[str]:
        if not chunks:
            return []
        ids = [str(uuid4()) for _ in chunks]
        points = [
            PointStruct(
                id=point_id,
                vector=chunk.vector,
                payload={
                    "doc_id": chunk.doc_id,
                    "chunk_id": chunk.chunk_id,
                    "page": chunk.page,
                    "account": chunk.account,
                    "entity_ids": chunk.entity_ids,
                    "text": chunk.text,
                },
            )
            for point_id, chunk in zip(ids, chunks)
        ]
        await self.client.upsert(collection_name=self.collection, points=points, wait=True)
        return ids

    async def delete(self, doc_id: str) -> bool:
        result = await self.client.delete(
            collection_name=self.collection,
            points_selector=FilterSelector(
                filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])
            ),
            wait=True,
        )
        return result.status == UpdateStatus.COMPLETED

    async def search(self, query_vector: list[float], doc_ids: list[str], limit: int) -> list[SearchResult]:
        # Never search without a doc filter, so results stay within the allowed documents
        if not doc_ids:
            return []
        response = await self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=Filter(must=[FieldCondition(key="doc_id", match=MatchAny(any=doc_ids))]),
            limit=limit,
            with_payload=True,
        )
        return [
            SearchResult(
                id=str(point.id),
                score=point.score,
                doc_id=point.payload["doc_id"],
                chunk_id=point.payload["chunk_id"],
                page=point.payload["page"],
                text=point.payload["text"],
                entity_ids=point.payload.get("entity_ids", []),
            )
            for point in response.points
        ]
