"""Hybrid retrieval (req 3.6) and the standard RAG baseline used by benchmarks (req 3.10)."""
from ..config import GLOBAL_SCOPE, get_settings
from ..stores import embedder
from . import graph_store, vector_store


def _scopes(user_id: str) -> list[str]:
    return [user_id, GLOBAL_SCOPE]


def _vector_hits(question: str, doc_ids: list[str], user_id: str) -> list[dict]:
    s = get_settings()
    vec = embedder().embed_query(question)
    hits = vector_store.search(vec, doc_ids, _scopes(user_id), s.top_k)
    return [h for h in hits if h["score"] >= s.min_score]


def _as_source(p: dict, origin: str, score: float | None) -> dict:
    return {"chunk_id": p["chunk_id"], "doc_id": p["doc_id"], "doc_name": p["doc_name"],
            "page": p["page"], "text": p["text"], "score": score, "origin": origin}


def standard_retrieve(user_id: str, question: str, doc_ids: list[str]) -> dict:
    hits = _vector_hits(question, doc_ids, user_id)
    return {"sources": [_as_source(h, "vector", h["score"]) for h in hits],
            "graph": {"nodes": [], "edges": [], "paths": []}, "graph_lines": []}


def hybrid_retrieve(user_id: str, question: str, doc_ids: list[str]) -> dict:
    s = get_settings()
    scopes = _scopes(user_id)
    hits = _vector_hits(question, doc_ids, user_id)
    sources = {h["chunk_id"]: _as_source(h, "vector", h["score"]) for h in hits}

    seeds = graph_store.seed_entities(question, list(sources), scopes)
    paths = graph_store.traverse(seeds, doc_ids, scopes, s.max_hops) if seeds else []

    nodes: dict[str, dict] = {}
    edges: dict[tuple, dict] = {}
    for p in paths:
        for n in p["nodes"]:
            nodes[n["id"]] = n
        for r in p["rels"]:
            edges[(r["source"], r["type"], r["target"], r["chunk_id"])] = r

    extra_ids = [r["chunk_id"] for r in edges.values() if r["chunk_id"] not in sources]
    for cid, payload in vector_store.get_chunks(list(dict.fromkeys(extra_ids))).items():
        sources[cid] = _as_source(payload, "graph", None)  # duplicates already excluded by dict key

    lines = []
    for r in edges.values():
        a, b = nodes.get(r["source"]), nodes.get(r["target"])
        src = sources.get(r["chunk_id"])
        where = f" [{src['doc_name']} p.{src['page']}]" if src else ""
        if a and b:
            lines.append(f"({a['name']}) -[{r['type']}]-> ({b['name']}){where}")

    return {
        "sources": list(sources.values()),
        "graph": {"nodes": list(nodes.values()), "edges": list(edges.values()),
                  "paths": [{"nodes": [n["id"] for n in p["nodes"]], "rels": p["rels"]} for p in paths]},
        "graph_lines": lines,
    }
