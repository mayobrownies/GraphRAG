from unittest.mock import AsyncMock

import pytest

from app.graph_schema import Entity, GraphChunk
from app.repositories.graph_store import GraphStore, StaleGraphWrite


@pytest.fixture
def store():
    result = GraphStore(driver=AsyncMock())
    result._read = AsyncMock(return_value=[])
    return result


async def test_no_documents_or_seeds_never_queries_database(store):
    assert await store.search("alice", []) == []
    assert await store.node_details("alice", [], "x") is None
    assert await store.traverse("alice", ["doc"], []) == []
    assert await store.expand("alice", [], "x") == []
    store._read.assert_not_called()


async def test_search_passes_literal_user_text_as_parameter(store):
    text = "x' MATCH (n) DETACH DELETE n //"
    await store.search("alice", ["doc", "doc"], text)
    query = store._read.call_args.args[0]
    params = store._read.call_args.kwargs
    assert text not in query
    assert params["account"] == "alice" and params["doc_ids"] == ["doc"]
    assert params["text"] == text.casefold()


@pytest.mark.parametrize("hops", [0, 3, True, "2"])
async def test_rejects_unbounded_or_non_integer_traversal(store, hops):
    with pytest.raises(ValueError):
        await store.traverse("alice", ["doc"], ["id"], hops=hops)
    store._read.assert_not_called()


@pytest.mark.parametrize("limit", [0, 201, True, "10"])
async def test_caps_query_result_limit(store, limit):
    with pytest.raises(ValueError):
        await store.search("alice", ["doc"], limit=limit)


async def test_invalid_account_cannot_issue_query(store):
    with pytest.raises(ValueError):
        await store.search("", ["doc"])
    store._read.assert_not_called()


async def test_stale_write_stops_before_any_data_is_inserted(store):
    calls = []
    async def run(tx, query, **params):
        calls.append(query)
        return []
    async def write(callback):
        return await callback(object())
    store._run = run
    store._write = write
    with pytest.raises(StaleGraphWrite):
        await store.upsert_chunk("alice", 1, GraphChunk("doc", "chunk", 1, "text", (Entity("g", "Gene"),)))
    assert len(calls) == 1


async def test_node_details_returns_none_for_inaccessible_node(store):
    assert await store.node_details("alice", ["doc"], "other-account-id") is None
