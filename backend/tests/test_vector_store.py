import pytest
from qdrant_client import AsyncQdrantClient

from app.repositories.vector_store import ChunkVector, VectorStore


def chunk(doc_id: str, chunk_id: str, vector: list[float]) -> ChunkVector:
    return ChunkVector(
        doc_id=doc_id,
        chunk_id=chunk_id,
        account="user-1",
        page=1,
        text=f"text of {chunk_id}",
        vector=vector,
        entity_ids=[f"entity-{chunk_id}"],
    )


@pytest.fixture
async def store():
    client = AsyncQdrantClient(location=":memory:")
    store = VectorStore(client=client, collection="test_chunks")
    await store.create_collection(vector_size=3)
    yield store
    await client.close()


async def count(store: VectorStore) -> int:
    return (await store.client.count(store.collection, exact=True)).count


async def test_create_collection_is_idempotent(store):
    assert await store.create_collection(vector_size=3) is False


async def test_create_collection_returns_true_when_new():
    client = AsyncQdrantClient(location=":memory:")
    store = VectorStore(client=client, collection="fresh")
    assert await store.create_collection(vector_size=3) is True
    await client.close()


async def test_insert_returns_one_id_per_chunk(store):
    ids = await store.insert([chunk("doc-a", "a1", [1, 0, 0]), chunk("doc-a", "a2", [0, 1, 0])])
    assert len(ids) == 2 and len(set(ids)) == 2
    assert await count(store) == 2


async def test_insert_empty_list(store):
    assert await store.insert([]) == []


async def test_search_ranks_by_similarity_and_filters_by_doc(store):
    await store.insert([
        chunk("doc-a", "a1", [1, 0, 0]),
        chunk("doc-a", "a2", [0, 1, 0]),
        chunk("doc-b", "b1", [1, 0, 0]),
    ])
    results = await store.search([0.9, 0.1, 0], doc_ids=["doc-a"], limit=5)
    assert [r.chunk_id for r in results] == ["a1", "a2"]
    assert results[0].score > results[1].score
    assert results[0].entity_ids == ["entity-a1"]
    assert results[0].page == 1 and results[0].text == "text of a1"


async def test_search_with_no_doc_ids_returns_nothing(store):
    await store.insert([chunk("doc-a", "a1", [1, 0, 0])])
    assert await store.search([1, 0, 0], doc_ids=[], limit=5) == []


async def test_delete_removes_only_that_doc(store):
    await store.insert([chunk("doc-a", "a1", [1, 0, 0]), chunk("doc-b", "b1", [0, 1, 0])])
    assert await store.delete("doc-a") is True
    assert await count(store) == 1
    assert await store.search([1, 0, 0], doc_ids=["doc-a"], limit=5) == []
    assert len(await store.search([1, 0, 0], doc_ids=["doc-b"], limit=5)) == 1
