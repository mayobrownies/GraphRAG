"""Async Neo4j storage, evidence-scoped queries and revision-fenced writes.

The caller must derive account from verified authentication and pass only
authorized, ready doc_ids to reads. This repository never grants document access.
Document revisions stop superseded ingestion jobs writing after replacement or
deletion. A coordinator still has to manage readiness across Neo4j and Qdrant.
"""
from dataclasses import dataclass

from neo4j import AsyncDriver, AsyncGraphDatabase, Query

from app.graph_schema import (
    GraphChunk, NODE_TYPES, RELATIONSHIP_TYPES, normalize_name, required_text, stable_id,
)

FACT_TYPES = "|".join(sorted(RELATIONSHIP_TYPES))
CONSTRAINTS = (
    "CREATE CONSTRAINT kg_entity_id IF NOT EXISTS FOR (e:KGEntity) REQUIRE e.entity_id IS UNIQUE",
    "CREATE CONSTRAINT kg_chunk_key IF NOT EXISTS FOR (c:KGChunk) REQUIRE c.key IS UNIQUE",
    "CREATE CONSTRAINT kg_document_key IF NOT EXISTS FOR (d:KGDocument) REQUIRE (d.account, d.doc_id) IS UNIQUE",
)


class StaleGraphWrite(ValueError):
    """The document was replaced or deleted after this job started."""


@dataclass
class GraphStore:
    driver: AsyncDriver
    database: str = "neo4j"
    query_timeout: float = 15.0

    @classmethod
    def connect(cls, uri: str, username: str, password: str, database: str = "neo4j"):
        for name, value in (("uri", uri), ("username", username), ("password", password), ("database", database)):
            required_text(value, name)
        return cls(AsyncGraphDatabase.driver(
            uri, auth=(username, password), connection_timeout=10,
            connection_acquisition_timeout=15, max_transaction_retry_time=15,
        ), database)

    async def close(self):
        await self.driver.close()

    async def verify_connection(self):
        await self.driver.verify_connectivity()
        async with self.driver.session(database=self.database) as session:
            await (await session.run(Query("RETURN 1 AS ok", timeout=self.query_timeout))).consume()

    async def create_constraints(self):
        async with self.driver.session(database=self.database) as session:
            for query in CONSTRAINTS:
                await (await session.run(Query(query, timeout=self.query_timeout))).consume()

    async def _run(self, tx, query, /, **params):
        result = await tx.run(query, **params)
        return await result.data()

    async def _read(self, query, /, **params):
        async with self.driver.session(database=self.database, default_access_mode="READ") as session:
            async def run(tx):
                return await self._run(tx, query, **params)
            run.timeout = self.query_timeout
            return await session.execute_read(run)

    async def _write(self, callback):
        callback.timeout = self.query_timeout
        async with self.driver.session(database=self.database) as session:
            return await session.execute_write(callback)

    @staticmethod
    def _scope(account, doc_ids):
        required_text(account, "account")
        return sorted({required_text(doc_id, "doc_id") for doc_id in doc_ids})

    @staticmethod
    def _limit(limit):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")

    async def _remove_document_data(self, tx, account, doc_id):
        await self._run(tx, f"MATCH ()-[r:{FACT_TYPES}]->() WHERE r.account=$account AND r.doc_id=$doc_id DELETE r", account=account, doc_id=doc_id)
        await self._run(tx, "MATCH (c:KGChunk {account:$account, doc_id:$doc_id}) DETACH DELETE c", account=account, doc_id=doc_id)
        await self._run(tx, "MATCH (e:KGEntity {account:$account}) WHERE NOT EXISTS { MATCH (:KGChunk)-[:MENTIONS]->(e) } DETACH DELETE e", account=account)

    async def begin_document(self, account: str, doc_id: str) -> int:
        """Start a new indexing revision, atomically clearing this document's old graph."""
        self._scope(account, [doc_id])
        async def begin(tx):
            rows = await self._run(tx, """
                MERGE (d:KGDocument {account:$account, doc_id:$doc_id})
                ON CREATE SET d.revision=0
                SET d.revision=d.revision+1, d.active=true
                RETURN d.revision AS revision
            """, account=account, doc_id=doc_id)
            await self._remove_document_data(tx, account, doc_id)
            return rows[0]["revision"]
        return await self._write(begin)

    async def upsert_chunk(self, account: str, revision: int, chunk: GraphChunk) -> list[str]:
        """Replace a chunk's accepted extraction in one transaction; return Qdrant entity_ids."""
        self._scope(account, [chunk.doc_id])
        if type(revision) is not int or revision < 1:
            raise ValueError("revision must be a positive integer")
        key = stable_id("graphrag-chunk-v1", account, chunk.doc_id, chunk.chunk_id)
        ids = sorted({entity.id_for(account) for entity in chunk.entities})
        async def insert(tx):
            # Acquire the same document lock as replacement/deletion before checking revision.
            rows = await self._run(tx, """
                MATCH (d:KGDocument {account:$account, doc_id:$doc_id})
                SET d.write_lock=coalesce(d.write_lock,0)+1
                WITH d WHERE d.active=true AND d.revision=$revision
                RETURN d.revision AS revision
            """, account=account, doc_id=chunk.doc_id, revision=revision)
            if not rows:
                raise StaleGraphWrite("Document revision is no longer active")
            await self._run(tx, f"MATCH ()-[r:{FACT_TYPES}]->() WHERE r.account=$account AND r.chunk_key=$key DELETE r", account=account, key=key)
            await self._run(tx, "MATCH (c:KGChunk {key:$key}) DETACH DELETE c", key=key)
            await self._run(tx, """
                CREATE (:KGChunk {key:$key, account:$account, doc_id:$doc_id,
                    chunk_id:$chunk_id, page:$page, text:$text, revision:$revision})
            """, key=key, account=account, doc_id=chunk.doc_id, chunk_id=chunk.chunk_id, page=chunk.page, text=chunk.text, revision=revision)
            for entity in chunk.entities:
                # node_type is a validated fixed label, never free-form LLM text.
                await self._run(tx, f"""
                    MERGE (e:KGEntity {{entity_id:$entity_id}})
                    ON CREATE SET e.account=$account, e.name=$name, e.node_type=$node_type
                    SET e:{entity.node_type}
                    WITH e MATCH (c:KGChunk {{key:$key}})
                    MERGE (c)-[:MENTIONS]->(e)
                """, entity_id=entity.id_for(account), account=account, name=normalize_name(entity.name), node_type=entity.node_type, key=key)
            for relationship in chunk.relationships:
                source = relationship.source.id_for(account)
                target = relationship.target.id_for(account)
                kind = relationship.relationship_type
                await self._run(tx, f"""
                    MATCH (a:KGEntity {{entity_id:$source, account:$account}}),
                          (b:KGEntity {{entity_id:$target, account:$account}})
                    MERGE (a)-[r:{kind} {{edge_id:$edge_id}}]->(b)
                    SET r.account=$account, r.doc_id=$doc_id, r.chunk_key=$key,
                        r.chunk_id=$chunk_id, r.page=$page
                """, source=source, target=target, account=account,
                    edge_id=stable_id("graphrag-edge-v1", key, source, kind, target),
                    doc_id=chunk.doc_id, key=key, chunk_id=chunk.chunk_id, page=chunk.page)
            await self._run(tx, "MATCH (e:KGEntity {account:$account}) WHERE NOT EXISTS { MATCH (:KGChunk)-[:MENTIONS]->(e) } DETACH DELETE e", account=account)
            return ids
        return await self._write(insert)

    async def delete_document(self, account: str, doc_id: str):
        """Keep a revision tombstone so a delayed old job cannot recreate deleted data."""
        self._scope(account, [doc_id])
        async def delete(tx):
            await self._run(tx, """
                MERGE (d:KGDocument {account:$account, doc_id:$doc_id})
                ON CREATE SET d.revision=0
                SET d.revision=d.revision+1, d.active=false
            """, account=account, doc_id=doc_id)
            await self._remove_document_data(tx, account, doc_id)
        await self._write(delete)

    async def search(self, account: str, doc_ids: list[str], text: str = "", node_type: str | None = None, limit: int = 50):
        docs = self._scope(account, doc_ids)
        self._limit(limit)
        if node_type is not None and node_type not in NODE_TYPES:
            raise ValueError("Unsupported node type")
        if not docs:
            return []
        return await self._read("""
            MATCH (c:KGChunk {account:$account})-[:MENTIONS]->(e:KGEntity {account:$account})
            WHERE c.doc_id IN $doc_ids AND ($node_type IS NULL OR e.node_type=$node_type)
                AND e.name CONTAINS $text
            RETURN e.entity_id AS entity_id, e.name AS name, e.node_type AS node_type,
                collect(DISTINCT {doc_id:c.doc_id, chunk_id:c.chunk_id, page:c.page}) AS sources
            ORDER BY name, entity_id LIMIT $limit
        """, account=account, doc_ids=docs, text=normalize_name(text) if text.strip() else "", node_type=node_type, limit=limit)

    async def node_details(self, account: str, doc_ids: list[str], entity_id: str):
        docs = self._scope(account, doc_ids)
        required_text(entity_id, "entity_id")
        if not docs:
            return None
        rows = await self._read("""
            MATCH (c:KGChunk {account:$account})-[:MENTIONS]->(e:KGEntity {account:$account, entity_id:$entity_id})
            WHERE c.doc_id IN $doc_ids
            RETURN e.entity_id AS entity_id, e.name AS name, e.node_type AS node_type,
                collect(DISTINCT {doc_id:c.doc_id, chunk_id:c.chunk_id, page:c.page, text:c.text}) AS sources
        """, account=account, doc_ids=docs, entity_id=entity_id)
        return rows[0] if rows else None

    async def traverse(self, account: str, doc_ids: list[str], entity_ids: list[str], hops: int = 2, limit: int = 50):
        """Return evidence-bearing paths. Every edge must be supported by a selected document."""
        docs = self._scope(account, doc_ids)
        self._limit(limit)
        if type(hops) is not int or hops not in (1, 2):
            raise ValueError("hops must be 1 or 2")
        seeds = sorted({required_text(value, "entity_id") for value in entity_ids})
        if not docs or not seeds:
            return []
        # Only the validated integer hop bound and fixed relationship types enter the template.
        return await self._read(f"""
            MATCH p=(seed:KGEntity {{account:$account}})-[:{FACT_TYPES}*1..{hops}]-(other:KGEntity)
            WHERE seed.entity_id IN $entity_ids
                AND all(n IN nodes(p) WHERE n.account=$account)
                AND all(n IN nodes(p) WHERE single(m IN nodes(p) WHERE m=n))
                AND all(r IN relationships(p) WHERE r.account=$account AND r.doc_id IN $doc_ids)
            WITH p ORDER BY length(p), [r IN relationships(p) | r.edge_id] LIMIT $limit
            RETURN [n IN nodes(p) | {{entity_id:n.entity_id, name:n.name, node_type:n.node_type}}] AS nodes,
                [r IN relationships(p) | {{edge_id:r.edge_id, relationship_type:type(r),
                    source:startNode(r).entity_id, target:endNode(r).entity_id,
                    doc_id:r.doc_id, chunk_id:r.chunk_id, page:r.page}}] AS edges
        """, account=account, doc_ids=docs, entity_ids=seeds, limit=limit)

    async def expand(self, account: str, doc_ids: list[str], entity_id: str, limit: int = 50):
        return await self.traverse(account, doc_ids, [entity_id], hops=1, limit=limit)
