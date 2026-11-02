"""Async Neo4j storage for the paper graph.

Reads trust the given doc_ids, so callers must pass only authorized, ready ones.
"""
from dataclasses import dataclass

from neo4j import AsyncDriver, AsyncGraphDatabase, Query

from app.graph_schema import MIN_WEIGHT, Paper, normalize_name, required_text

CONSTRAINTS = (
    "CREATE CONSTRAINT paper_doc_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.doc_id IS UNIQUE",
    "CREATE CONSTRAINT paper_graph_lock IF NOT EXISTS FOR (l:PaperGraphLock) REQUIRE l.name IS UNIQUE",
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
    def _scope(doc_ids, field="doc_id"):
        return sorted({required_text(doc_id, field) for doc_id in doc_ids})

    @staticmethod
    def _limit(value, field="limit"):
        if type(value) is not int or not 1 <= value <= 200:
            raise ValueError(f"{field} must be between 1 and 200")

    async def _lock(self, tx):
        # Serializes paper writes so papers added at the same time still link to each other.
        await self._run(tx, "MERGE (l:PaperGraphLock {name:'papers'}) SET l.writes=coalesce(l.writes,0)+1")

    async def _remove_edges(self, tx, doc_id):
        await self._run(tx, "MATCH (:Paper {doc_id:$doc_id})-[r:ASSOCIATED_WITH]-() DELETE r", doc_id=doc_id)

    async def begin_document(self, account: str, doc_id: str) -> int:
        """Start a new revision and clear the paper's old embedding and edges."""
        required_text(account, "account")
        self._scope([doc_id])
        async def begin(tx):
            await self._lock(tx)
            rows = await self._run(tx, """
                MERGE (p:Paper {doc_id:$doc_id})
                ON CREATE SET p.revision=0
                SET p.revision=p.revision+1, p.active=true, p.account=$account
                REMOVE p.embedding
                RETURN p.revision AS revision
            """, account=account, doc_id=doc_id)
            await self._remove_edges(tx, doc_id)
            return rows[0]["revision"]
        return await self._write(begin)

    async def add_paper(self, account: str, revision: int, paper: Paper, min_weight: float = MIN_WEIGHT) -> list[dict]:
        """Store the embedding and link the paper to every active paper at or above min_weight."""
        required_text(account, "account")
        if type(revision) is not int or revision < 1:
            raise ValueError("revision must be a positive integer")
        if type(min_weight) not in (int, float) or not -1 <= min_weight <= 1:
            raise ValueError("min_weight must be between -1 and 1")
        async def insert(tx):
            await self._lock(tx)
            rows = await self._run(tx, """
                MATCH (p:Paper {doc_id:$doc_id})
                WHERE p.active=true AND p.revision=$revision AND p.account=$account
                SET p.name=$name, p.search_name=$search_name, p.embedding=$embedding
                RETURN p.doc_id AS doc_id
            """, doc_id=paper.doc_id, revision=revision, account=account, name=paper.name,
                search_name=normalize_name(paper.name), embedding=list(paper.embedding))
            if not rows:
                raise StaleGraphWrite("Document revision is no longer active")
            await self._remove_edges(tx, paper.doc_id)
            # vector.similarity.cosine is scaled to [0, 1]; convert back to [-1, 1].
            return await self._run(tx, """
                MATCH (p:Paper {doc_id:$doc_id}), (o:Paper)
                WHERE o.active=true AND o.embedding IS NOT NULL AND o.doc_id<>p.doc_id
                WITH p, o, 2*vector.similarity.cosine(p.embedding, o.embedding)-1 AS weight
                WHERE weight >= $min_weight
                CREATE (p)-[:ASSOCIATED_WITH {weight:weight}]->(o)
                RETURN o.doc_id AS doc_id, weight
                ORDER BY weight DESC, doc_id
            """, doc_id=paper.doc_id, min_weight=min_weight)
        return await self._write(insert)

    async def delete_document(self, account: str, doc_id: str):
        """Leave a tombstone so a late job cannot recreate the paper."""
        required_text(account, "account")
        self._scope([doc_id])
        async def delete(tx):
            await self._lock(tx)
            await self._run(tx, """
                MERGE (p:Paper {doc_id:$doc_id})
                ON CREATE SET p.revision=0, p.account=$account
                SET p.revision=p.revision+1, p.active=false
                REMOVE p.embedding, p.name, p.search_name
            """, account=account, doc_id=doc_id)
            await self._remove_edges(tx, doc_id)
        await self._write(delete)

    async def graph(self, doc_ids: list[str], text: str = "", limit: int = 50, per_paper: int = 5) -> dict:
        """Selected papers whose names contain text, with each one's strongest links among them."""
        docs = self._scope(doc_ids)
        self._limit(limit)
        self._limit(per_paper, "per_paper")
        if not docs:
            return {"nodes": [], "edges": []}
        nodes = await self._read("""
            MATCH (p:Paper)
            WHERE p.doc_id IN $doc_ids AND p.active=true AND p.embedding IS NOT NULL
                AND p.search_name CONTAINS $text
            RETURN p.doc_id AS doc_id, p.name AS name
            ORDER BY name, doc_id LIMIT $limit
        """, doc_ids=docs, text=normalize_name(text) if text.strip() else "", limit=limit)
        ids = [node["doc_id"] for node in nodes]
        if not ids:
            return {"nodes": [], "edges": []}
        edges = await self._read("""
            MATCH (p:Paper)-[r:ASSOCIATED_WITH]-(o:Paper)
            WHERE p.doc_id IN $ids AND o.doc_id IN $ids
            WITH p, r, o ORDER BY r.weight DESC, o.doc_id
            WITH p, collect(r)[..$per_paper] AS strongest
            UNWIND strongest AS r
            WITH DISTINCT r
            RETURN startNode(r).doc_id AS source, endNode(r).doc_id AS target, r.weight AS weight
            ORDER BY weight DESC, source, target
        """, ids=ids, per_paper=per_paper)
        return {"nodes": nodes, "edges": edges}

    async def neighbors(self, doc_ids: list[str], seed_ids: list[str], per_paper: int = 5) -> list[dict]:
        """Each seed's strongest links to other selected papers."""
        docs = self._scope(doc_ids)
        seeds = self._scope(seed_ids, "seed_id")
        self._limit(per_paper, "per_paper")
        if not docs or not seeds:
            return []
        return await self._read("""
            MATCH (s:Paper)-[r:ASSOCIATED_WITH]-(o:Paper)
            WHERE s.doc_id IN $seeds AND s.doc_id IN $doc_ids AND o.doc_id IN $doc_ids
            WITH s, r, o ORDER BY r.weight DESC, o.doc_id
            WITH s, collect({doc_id:o.doc_id, name:o.name, weight:r.weight})[..$per_paper] AS linked
            UNWIND linked AS link
            RETURN s.doc_id AS seed, link.doc_id AS doc_id, link.name AS name, link.weight AS weight
            ORDER BY seed, weight DESC, doc_id
        """, doc_ids=docs, seeds=seeds, per_paper=per_paper)
