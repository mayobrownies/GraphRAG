from unittest.mock import AsyncMock

import pytest

from app.graph_schema import Paper
from app.repositories.graph_store import GraphStore, StaleGraphWrite


@pytest.fixture
def store():
    result = GraphStore(driver=AsyncMock())
    result._read = AsyncMock(return_value=[])
    return result


async def test_no_documents_or_seeds_never_queries_database(store):
    assert await store.graph([]) == {"nodes": [], "edges": []}
    assert await store.neighbors([], ["doc"]) == []
    assert await store.neighbors(["doc"], []) == []
    store._read.assert_not_called()


async def test_graph_without_matching_papers_skips_edge_query(store):
    assert await store.graph(["doc"]) == {"nodes": [], "edges": []}
    assert store._read.call_count == 1


async def test_search_passes_literal_user_text_as_parameter(store):
    text = "x' MATCH (n) DETACH DELETE n //"
    await store.graph(["doc", "doc"], text)
    query = store._read.call_args.args[0]
    params = store._read.call_args.kwargs
    assert text not in query
    assert params["doc_ids"] == ["doc"]
    assert params["text"] == text.casefold()


@pytest.mark.parametrize("value", [0, 201, True, "10"])
async def test_caps_limit_and_per_paper(store, value):
    with pytest.raises(ValueError):
        await store.graph(["doc"], limit=value)
    with pytest.raises(ValueError):
        await store.neighbors(["doc"], ["doc"], per_paper=value)
    store._read.assert_not_called()


async def test_invalid_doc_id_cannot_issue_query(store):
    with pytest.raises(ValueError):
        await store.graph([""])
    with pytest.raises(ValueError):
        await store.neighbors(["doc"], [" "])
    store._read.assert_not_called()


@pytest.mark.parametrize("revision,min_weight", [(0, 0.3), (True, 0.3), (1, 1.5), (1, "0.3")])
async def test_add_paper_rejects_bad_revision_or_weight(store, revision, min_weight):
    with pytest.raises(ValueError):
        await store.add_paper("alice", revision, Paper("doc", "name", [1.0]), min_weight=min_weight)


async def test_stale_write_stops_before_any_edge_is_written(store):
    calls = []
    async def run(tx, query, **params):
        calls.append(query)
        return []
    async def write(callback):
        return await callback(object())
    store._run = run
    store._write = write
    with pytest.raises(StaleGraphWrite):
        await store.add_paper("alice", 1, Paper("doc", "name", [1.0, 0.0]))
    assert len(calls) == 2 and not any("ASSOCIATED_WITH" in query for query in calls)
