"""Opt-in tests against real Neo4j; creates only UUID-namespaced synthetic data.

Set NEO4J_TEST_URI, NEO4J_TEST_USERNAME, NEO4J_TEST_PASSWORD and optionally
NEO4J_TEST_DATABASE. These are never read from production environment names.
"""
import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio

from app.graph_schema import Entity, GraphChunk, Relationship
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
        yield store, account, other
    finally:
        # Only delete records owned by the unique test accounts created above.
        async with store.driver.session(database=store.database) as session:
            result = await session.run("MATCH (n) WHERE n.account IN $accounts DETACH DELETE n", accounts=[account, other])
            await result.consume()
        await store.close()


def sample(doc, chunk, page=1):
    gene, protein, disease = Entity("BRCA1", "Gene"), Entity("protein a", "Protein"), Entity("disease a", "Disease")
    return GraphChunk(doc, chunk, page, "Synthetic test evidence", (gene, protein, disease), (
        Relationship(gene, protein, "ENCODES"), Relationship(protein, disease, "ASSOCIATED_WITH"),
    ))


async def test_repeat_ingestion_has_stable_ids_and_no_duplicate_evidence(live):
    store, account, _ = live
    revision = await store.begin_document(account, "doc-a")
    ids = await store.upsert_chunk(account, revision, sample("doc-a", "c1"))
    assert ids == await store.upsert_chunk(account, revision, sample("doc-a", "c1"))
    nodes = await store.search(account, ["doc-a"])
    assert len(nodes) == 3 and all(len(node["sources"]) == 1 for node in nodes)
    paths = await store.traverse(account, ["doc-a"], [Entity("BRCA1", "Gene").id_for(account)])
    assert sorted(len(path["edges"]) for path in paths) == [1, 2]
    assert all(edge["chunk_id"] == "c1" and edge["page"] == 1 for path in paths for edge in path["edges"])


async def test_every_edge_and_source_is_filtered_by_account_and_selected_docs(live):
    store, account, other = live
    for owner, doc in [(account, "doc-a"), (account, "doc-b"), (other, "doc-a")]:
        revision = await store.begin_document(owner, doc)
        await store.upsert_chunk(owner, revision, sample(doc, "same-chunk-id", page=2 if doc == "doc-b" else 1))
    gene_id = Entity("BRCA1", "Gene").id_for(account)
    paths = await store.traverse(account, ["doc-a"], [gene_id])
    assert paths and all(edge["doc_id"] == "doc-a" for path in paths for edge in path["edges"])
    assert await store.traverse(other, ["doc-a"], [gene_id]) == []
    details = await store.node_details(account, ["doc-a"], gene_id)
    assert len(details["sources"]) == 1 and details["sources"][0]["page"] == 1
    assert await store.search(account, []) == []


async def test_delete_keeps_shared_evidence_and_rejects_old_job(live):
    store, account, _ = live
    revision_a = await store.begin_document(account, "doc-a")
    await store.upsert_chunk(account, revision_a, sample("doc-a", "c1"))
    revision_b = await store.begin_document(account, "doc-b")
    await store.upsert_chunk(account, revision_b, sample("doc-b", "c2"))
    await store.delete_document(account, "doc-a")
    assert await store.search(account, ["doc-a"]) == []
    assert len(await store.search(account, ["doc-b"])) == 3
    with pytest.raises(StaleGraphWrite):
        await store.upsert_chunk(account, revision_a, sample("doc-a", "c1"))
    await store.delete_document(account, "doc-b")
    assert await store.search(account, ["doc-a", "doc-b"]) == []


async def test_replacement_and_chunk_update_remove_old_facts(live):
    store, account, _ = live
    first = await store.begin_document(account, "doc-a")
    await store.upsert_chunk(account, first, sample("doc-a", "c1"))
    new = await store.begin_document(account, "doc-a")
    with pytest.raises(StaleGraphWrite):
        await store.upsert_chunk(account, first, sample("doc-a", "c1"))
    await store.upsert_chunk(account, new, sample("doc-a", "c1"))
    await store.upsert_chunk(account, new, GraphChunk("doc-a", "c1", 3, "Replacement text", (Entity("new gene", "Gene"),)))
    nodes = await store.search(account, ["doc-a"])
    assert len(nodes) == 1 and nodes[0]["name"] == "new gene"
    assert nodes[0]["sources"][0]["page"] == 3


async def test_search_filters_and_paths_cannot_bridge_an_unselected_document(live):
    store, account, _ = live
    gene, protein, disease = Entity("BRCA1", "Gene"), Entity("protein a", "Protein"), Entity("disease a", "Disease")
    for doc, entities, relationship in (
        ("selected", (gene, protein), Relationship(gene, protein, "ENCODES")),
        ("hidden", (protein, disease), Relationship(protein, disease, "ASSOCIATED_WITH")),
    ):
        revision = await store.begin_document(account, doc)
        await store.upsert_chunk(account, revision, GraphChunk(doc, "c1", 1, "Evidence", entities, (relationship,)))
    assert [node["entity_id"] for node in await store.search(account, ["selected"], "  BRCA1  ", "Gene")] == [gene.id_for(account)]
    assert await store.search(account, ["selected"], "BRCA1", "Drug") == []
    assert await store.search(account, ["selected"], "x' MATCH (n) DETACH DELETE n //") == []
    assert await store.node_details(account, ["selected"], disease.id_for(account)) is None
    selected = await store.traverse(account, ["selected"], [gene.id_for(account)])
    assert [len(path["edges"]) for path in selected] == [1]
    both = await store.traverse(account, ["selected", "hidden"], [gene.id_for(account)])
    assert sorted(len(path["edges"]) for path in both) == [1, 2]
    reverse = await store.expand(account, ["selected"], protein.id_for(account))
    assert len(reverse) == 1
    assert reverse[0]["edges"][0]["source"] == gene.id_for(account)
    assert reverse[0]["edges"][0]["target"] == protein.id_for(account)


async def test_failed_chunk_replacement_rolls_back_previous_evidence(live, monkeypatch):
    store, account, _ = live
    revision = await store.begin_document(account, "doc-a")
    await store.upsert_chunk(account, revision, sample("doc-a", "c1"))
    run = store._run

    async def fail_after_chunk_creation(tx, query, **params):
        rows = await run(tx, query, **params)
        if "CREATE (:KGChunk" in query:
            raise RuntimeError("Simulated extraction write failure")
        return rows

    with monkeypatch.context() as patch:
        patch.setattr(store, "_run", fail_after_chunk_creation)
        with pytest.raises(RuntimeError, match="Simulated extraction write failure"):
            await store.upsert_chunk(account, revision, GraphChunk("doc-a", "c1", 9, "Incomplete replacement", (Entity("new gene", "Gene"),)))
    nodes = await store.search(account, ["doc-a"])
    assert len(nodes) == 3 and all(node["sources"][0]["page"] == 1 for node in nodes)
    assert len(await store.traverse(account, ["doc-a"], [Entity("BRCA1", "Gene").id_for(account)])) == 2


async def test_concurrent_revisions_and_chunk_writes_remain_consistent(live):
    store, account, _ = live
    revisions = await asyncio.gather(*(store.begin_document(account, "doc-a") for _ in range(3)))
    assert sorted(revisions) == [1, 2, 3]
    with pytest.raises(StaleGraphWrite):
        await store.upsert_chunk(account, min(revisions), sample("doc-a", "old"))
    revision = max(revisions)
    await asyncio.gather(*(store.upsert_chunk(account, revision, sample("doc-a", f"c{i}")) for i in range(4)))
    nodes = await store.search(account, ["doc-a"])
    assert len(nodes) == 3 and all(len(node["sources"]) == 4 for node in nodes)
    await store.delete_document(account, "doc-a")
    assert await store.search(account, ["doc-a"]) == []
    with pytest.raises(StaleGraphWrite):
        await store.upsert_chunk(account, revision, sample("doc-a", "late"))
