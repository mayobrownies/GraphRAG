"""GraphStore with a recording Neo4j driver: checks parameters, whitelisting and statement shape."""
from app.schema import validate_extraction
from app.services import graph_store


class _Rec:
    def __init__(self):
        self.calls = []

    def run(self, q, **params):
        self.calls.append((" ".join(q.split()), params))
        return type("R", (), {"single": lambda s: None, "__iter__": lambda s: iter([])})()

    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Driver:
    def __init__(self): self.s = _Rec()
    def session(self): return self.s


def test_write_document_statements(monkeypatch):
    d = _Driver()
    monkeypatch.setattr(graph_store, "neo4j_driver", lambda: d)
    ex = validate_extraction({"entities": [{"name": "Metformin", "type": "Drug"}, {"name": "T2D", "type": "Disease"}],
                              "relations": [{"source": "Metformin", "target": "T2D", "type": "TREATS"}]}, "u1")
    graph_store.write_document("doc1", "p.pdf", "u1", [{"id": "c1", "page": 3}], {"c1": ex})
    qs = [q for q, _ in d.s.calls]
    assert any("MERGE (a)-[x:TREATS {doc_id:r.doc_id, chunk_id:r.chunk_id}]->(b)" in q for q in qs)
    rel_params = next(p for q, p in d.s.calls if "TREATS" in q)["rels"]
    assert rel_params[0]["doc_id"] == "doc1" and rel_params[0]["chunk_id"] == "c1"
    assert any(p.get("page") == 3 for _, p in d.s.calls)


def test_traverse_caps_hops_and_parametrizes(monkeypatch):
    d = _Driver()
    monkeypatch.setattr(graph_store, "neo4j_driver", lambda: d)
    graph_store.traverse(["a"], ["d1"], ["u1", "global"], hops=99)
    q, params = d.s.calls[0]
    assert "[*1..4]" in q and params["docs"] == ["d1"] and params["scopes"] == ["u1", "global"]
