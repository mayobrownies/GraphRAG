"""Opt-in tests against real Neo4j. Set NEO4J_TEST_URI, NEO4J_TEST_USERNAME and NEO4J_TEST_PASSWORD."""
import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio

from app.graph_schema import Paper
from app.repositories.graph_store import GraphStore, StaleGraphWrite

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def live():
    names = ("NEO4J_TEST_URI", "NEO4J_TEST_USERNAME", "NEO4J_TEST_PASSWORD")
    if not all(os.getenv(name) for name in names):
        pytest.skip("Set NEO4J_TEST_* variables to run real Neo4j tests")
    store = GraphStore.connect(*(os.environ[name] for name in names), database=os.getenv("NEO4J_TEST_DATABASE", "neo4j"))
    prefix = "graphrag-test-" + str(uuid4())
    account, other = prefix + "-a", prefix + "-b"
    await store.verify_connection()
    await store.create_constraints()
    try:
        yield store, account, other, lambda name: f"{prefix}-{name}"
    finally:
        async with store.driver.session(database=store.database) as session:
            result = await session.run("MATCH (n) WHERE n.account IN $accounts DETACH DELETE n", accounts=[account, other])
            await result.consume()
        await store.close()


async def add(store, account, doc_id, embedding, name=None, **kwargs):
    revision = await store.begin_document(account, doc_id)
    return await store.add_paper(account, revision, Paper(doc_id, name or doc_id, embedding), **kwargs)


async def test_weight_is_plain_cosine_similarity(live):
    store, account, _, doc = live
    await add(store, account, doc("a"), [1.0, 0.0])
    links = await add(store, account, doc("b"), [2.0, 0.0])
    assert links == [{"doc_id": doc("a"), "weight": pytest.approx(1.0)}]
    assert await add(store, account, doc("c"), [0.0, 1.0]) == []
    opposite = await add(store, account, doc("d"), [-1.0, 0.0], min_weight=-1)
    assert {link["doc_id"]: link["weight"] for link in opposite} == {
        doc("a"): pytest.approx(-1.0), doc("b"): pytest.approx(-1.0), doc("c"): pytest.approx(0.0),
    }


async def test_graph_and_neighbors_only_show_selected_papers(live):
    store, account, other, doc = live
    await add(store, account, doc("a"), [1.0, 0.0], "BRCA1 Review")
    await add(store, account, doc("b"), [0.9, 0.1], "PARP1 Mechanism")
    await add(store, other, doc("hidden"), [1.0, 0.05], "Hidden Paper")
    graph = await store.graph([doc("a"), doc("b")])
    assert [node["doc_id"] for node in graph["nodes"]] == [doc("a"), doc("b")]
    assert len(graph["edges"]) == 1
    assert {graph["edges"][0]["source"], graph["edges"][0]["target"]} == {doc("a"), doc("b")}
    assert [node["name"] for node in (await store.graph([doc("a"), doc("b")], "  brca1 "))["nodes"]] == ["BRCA1 Review"]
    assert await store.graph([doc("a"), doc("b")], "x' MATCH (n) DETACH DELETE n //") == {"nodes": [], "edges": []}
    linked = await store.neighbors([doc("a"), doc("b")], [doc("a")])
    assert [(row["seed"], row["doc_id"]) for row in linked] == [(doc("a"), doc("b"))]
    assert await store.neighbors([doc("b")], [doc("a")]) == []


async def test_per_paper_keeps_only_strongest_links(live):
    store, account, _, doc = live
    await add(store, account, doc("seed"), [1.0, 0.0])
    for name, embedding in (("close", [1.0, 0.1]), ("middle", [1.0, 0.5]), ("far", [1.0, 0.9])):
        await add(store, account, doc(name), embedding)
    ids = [doc(name) for name in ("seed", "close", "middle", "far")]
    linked = await store.neighbors(ids, [doc("seed")], per_paper=2)
    assert [row["doc_id"] for row in linked] == [doc("close"), doc("middle")]
    assert len((await store.graph(ids, per_paper=1))["edges"]) < len((await store.graph(ids, per_paper=3))["edges"])


async def test_reindex_and_delete_remove_edges_and_reject_old_jobs(live):
    store, account, _, doc = live
    await add(store, account, doc("a"), [1.0, 0.0])
    first = await store.begin_document(account, doc("b"))
    await store.add_paper(account, first, Paper(doc("b"), "b", [1.0, 0.0]))
    second = await store.begin_document(account, doc("b"))
    assert [node["doc_id"] for node in (await store.graph([doc("a"), doc("b")]))["nodes"]] == [doc("a")]
    with pytest.raises(StaleGraphWrite):
        await store.add_paper(account, first, Paper(doc("b"), "b", [1.0, 0.0]))
    await store.add_paper(account, second, Paper(doc("b"), "b", [0.0, 1.0]))
    assert (await store.graph([doc("a"), doc("b")]))["edges"] == []
    await store.delete_document(account, doc("a"))
    assert [node["doc_id"] for node in (await store.graph([doc("a"), doc("b")]))["nodes"]] == [doc("b")]
    with pytest.raises(StaleGraphWrite):
        await store.add_paper(account, second, Paper(doc("a"), "a", [1.0, 0.0]))


async def test_another_account_cannot_write_to_a_paper(live):
    store, account, other, doc = live
    revision = await store.begin_document(account, doc("a"))
    with pytest.raises(StaleGraphWrite):
        await store.add_paper(other, revision, Paper(doc("a"), "a", [1.0, 0.0]))


async def test_concurrent_papers_link_exactly_once_per_pair(live):
    store, account, _, doc = live
    ids = [doc(f"p{i}") for i in range(4)]
    revisions = [await store.begin_document(account, doc_id) for doc_id in ids]
    await asyncio.gather(*(store.add_paper(account, r, Paper(d, d, [1.0, 0.0])) for d, r in zip(ids, revisions)))
    graph = await store.graph(ids, per_paper=10)
    pairs = [frozenset((edge["source"], edge["target"])) for edge in graph["edges"]]
    assert len(pairs) == 6 and len(set(pairs)) == 6
