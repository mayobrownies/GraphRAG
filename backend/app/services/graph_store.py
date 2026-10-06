"""Neo4j Knowledge Graph store (req 3.5.3, 3.6.3, 3.9). Labels and types are whitelisted."""
from collections import defaultdict

from ..schema import REL_TYPES, ValidatedExtraction
from ..stores import neo4j_driver


def init_constraints() -> None:
    with neo4j_driver().session() as s:
        s.run("CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE")
        s.run("CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
        s.run("CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE")
        s.run("CREATE INDEX entity_scope IF NOT EXISTS FOR (e:Entity) ON (e.scope)")


def write_document(doc_id: str, name: str, scope: str, chunks: list[dict],
                   extractions: dict[str, ValidatedExtraction]) -> None:
    with neo4j_driver().session() as s:
        s.run("MERGE (d:Document {id:$id}) SET d.name=$name, d.scope=$scope", id=doc_id, name=name, scope=scope)
        for c in chunks:
            s.run(
                "MATCH (d:Document {id:$doc}) "
                "MERGE (c:Chunk {id:$id}) SET c.doc_id=$doc, c.page=$page, c.scope=$scope "
                "MERGE (d)-[:HAS_CHUNK]->(c)",
                doc=doc_id, id=c["id"], page=c["page"], scope=scope)
            ex = extractions.get(c["id"])
            if not ex:
                continue
            if ex.entities:
                s.run(
                    "UNWIND $ents AS e "
                    "MERGE (n:Entity {id:e.id}) "
                    "ON CREATE SET n.name=e.name, n.norm=e.norm, n.type=e.type, n.scope=e.scope "
                    "WITH n MATCH (c:Chunk {id:$cid}) MERGE (c)-[:MENTIONS]->(n)",
                    ents=ex.entities, cid=c["id"])
            by_type = defaultdict(list)
            for r in ex.relations:
                by_type[r["type"]].append({**r, "doc_id": doc_id, "chunk_id": c["id"]})
            for rtype, rels in by_type.items():
                assert rtype in REL_TYPES  # whitelist guard before interpolation
                s.run(
                    f"UNWIND $rels AS r MATCH (a:Entity {{id:r.a}}), (b:Entity {{id:r.b}}) "
                    f"MERGE (a)-[x:{rtype} {{doc_id:r.doc_id, chunk_id:r.chunk_id}}]->(b)",
                    rels=rels)


def delete_document(doc_id: str) -> None:
    with neo4j_driver().session() as s:
        rec = s.run(
            "MATCH (d:Document {id:$id})-[:HAS_CHUNK]->(:Chunk)-[:MENTIONS]->(e:Entity) "
            "RETURN collect(DISTINCT e.id) AS ids", id=doc_id).single()
        ids = rec["ids"] if rec else []
        s.run("MATCH ()-[r]->() WHERE r.doc_id = $id DELETE r", id=doc_id)
        s.run("MATCH (d:Document {id:$id}) OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk) DETACH DELETE c, d", id=doc_id)
        if ids:
            s.run("MATCH (e:Entity) WHERE e.id IN $ids AND NOT (e)<-[:MENTIONS]-() DETACH DELETE e", ids=ids)


def seed_entities(question: str, chunk_ids: list[str], scopes: list[str]) -> list[str]:
    with neo4j_driver().session() as s:
        from_chunks = s.run(
            "MATCH (c:Chunk)-[:MENTIONS]->(e:Entity) WHERE c.id IN $ids AND e.scope IN $scopes "
            "RETURN DISTINCT e.id AS id", ids=chunk_ids, scopes=scopes)
        ids = {r["id"] for r in from_chunks}
        from_query = s.run(
            "MATCH (e:Entity) WHERE e.scope IN $scopes AND size(e.norm) > 2 "
            "AND toLower($q) CONTAINS e.norm RETURN e.id AS id LIMIT 25", q=question, scopes=scopes)
        ids |= {r["id"] for r in from_query}
    return list(ids)


def traverse(seeds: list[str], doc_ids: list[str], scopes: list[str], hops: int, limit: int = 25) -> list[dict]:
    """Multi-hop Cypher traversal restricted to authorized documents and scopes."""
    hops = max(1, min(int(hops), 4))
    q = f"""
    MATCH p=(s:Entity)-[*1..{hops}]-(t:Entity)
    WHERE s.id IN $seeds
      AND all(n IN nodes(p) WHERE n:Entity AND n.scope IN $scopes)
      AND all(r IN relationships(p) WHERE r.doc_id IN $docs)
    RETURN [n IN nodes(p) | {{id:n.id, name:n.name, type:n.type}}] AS nodes,
           [r IN relationships(p) | {{type:type(r), source:startNode(r).id,
                                      target:endNode(r).id, doc_id:r.doc_id, chunk_id:r.chunk_id}}] AS rels
    LIMIT $limit
    """
    with neo4j_driver().session() as s:
        return [dict(r) for r in s.run(q, seeds=seeds, scopes=scopes, docs=doc_ids, limit=limit)]


def overview(scopes: list[str], doc_ids: list[str], search: str, types: list[str], limit: int) -> dict:
    with neo4j_driver().session() as s:
        nodes = [dict(r) for r in s.run(
            "MATCH (e:Entity)<-[:MENTIONS]-(c:Chunk) "
            "WHERE e.scope IN $scopes AND c.doc_id IN $docs "
            "AND ($search = '' OR toLower(e.name) CONTAINS $search) "
            "AND (size($types) = 0 OR e.type IN $types) "
            "WITH e, count(c) AS freq ORDER BY freq DESC LIMIT $limit "
            "RETURN e.id AS id, e.name AS name, e.type AS type, freq",
            scopes=scopes, docs=doc_ids, search=search.lower(), types=types, limit=limit)]
        ids = [n["id"] for n in nodes]
        edges = _edges_among(s, ids, doc_ids)
    return {"nodes": nodes, "edges": edges}


def expand(node_id: str, scopes: list[str], doc_ids: list[str], limit: int = 30) -> dict:
    with neo4j_driver().session() as s:
        rows = list(s.run(
            "MATCH (a:Entity {id:$id})-[r]-(b:Entity) "
            "WHERE r.doc_id IN $docs AND b.scope IN $scopes "
            "RETURN b.id AS id, b.name AS name, b.type AS type, type(r) AS rtype, "
            "startNode(r).id AS source, endNode(r).id AS target, r.doc_id AS doc_id, r.chunk_id AS chunk_id "
            "LIMIT $limit", id=node_id, docs=doc_ids, scopes=scopes, limit=limit))
    nodes = {r["id"]: {"id": r["id"], "name": r["name"], "type": r["type"]} for r in rows}
    edges = [{"type": r["rtype"], "source": r["source"], "target": r["target"],
              "doc_id": r["doc_id"], "chunk_id": r["chunk_id"]} for r in rows]
    return {"nodes": list(nodes.values()), "edges": edges}


def node_sources(node_id: str, doc_ids: list[str], limit: int = 20) -> list[dict]:
    with neo4j_driver().session() as s:
        return [dict(r) for r in s.run(
            "MATCH (e:Entity {id:$id})<-[:MENTIONS]-(c:Chunk)<-[:HAS_CHUNK]-(d:Document) "
            "WHERE c.doc_id IN $docs RETURN d.id AS doc_id, d.name AS doc_name, c.id AS chunk_id, c.page AS page "
            "LIMIT $limit", id=node_id, docs=doc_ids, limit=limit)]


def node_info(node_id: str) -> dict | None:
    with neo4j_driver().session() as s:
        r = s.run("MATCH (e:Entity {id:$id}) RETURN e.id AS id, e.name AS name, e.type AS type", id=node_id).single()
        return dict(r) if r else None


def _edges_among(session, ids: list[str], doc_ids: list[str]) -> list[dict]:
    if not ids:
        return []
    res = session.run(
        "MATCH (a:Entity)-[r]->(b:Entity) WHERE a.id IN $ids AND b.id IN $ids AND r.doc_id IN $docs "
        "RETURN type(r) AS type, a.id AS source, b.id AS target, r.doc_id AS doc_id, r.chunk_id AS chunk_id",
        ids=ids, docs=doc_ids)
    return [dict(r) for r in res]
