"""Fixtures: real FastAPI app and real Qdrant (in-memory) with in-memory fakes for
Supabase, Neo4j and Ollama, so the whole request path can be exercised without services."""
import hashlib
import itertools
import os

os.environ.update({
    "SUPABASE_URL": "http://supabase.test", "SUPABASE_SERVICE_KEY": "service",
    "NEO4J_PASSWORD": "pw", "EMBED_DIM": "32", "MIN_SCORE": "0.05",
})

import pytest
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient

from app import auth, repo
from app.config import GLOBAL_SCOPE, get_settings
from app.routers import documents as documents_router
from app.services import graph_store, llm, pipeline, retrieval, vector_store


# ---------- PDF builder ----------
def make_pdf(pages: list[str]) -> bytes:
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 3 0 R >> >> >>".encode())
        stream = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode() if text else b""
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()
    return out


# ---------- Fake Supabase ----------
class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload = db, name, [], "select", None
        self._order = self._limit = None

    def select(self, *_): self.op = "select"; return self
    def insert(self, row): self.op, self.payload = "insert", row; return self
    def update(self, fields): self.op, self.payload = "update", fields; return self
    def upsert(self, row): self.op, self.payload = "upsert", row; return self
    def delete(self): self.op = "delete"; return self
    def eq(self, k, v): self.filters.append(lambda r: r.get(k) == v); return self
    def order(self, k, desc=False): self._order = (k, desc); return self
    def limit(self, n): self._limit = n; return self

    def or_(self, expr):
        conds = []
        for part in expr.split(","):
            k, _op, v = part.split(".", 2)
            conds.append((k, True if v == "true" else v))
        self.filters.append(lambda r: any(r.get(k) == v for k, v in conds))
        return self

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        match = lambda r: all(f(r) for f in self.filters)
        if self.op == "insert":
            row = dict(self.payload, created_at=next(self.db.clock))
            rows.append(row)
            return _Res([row])
        if self.op == "upsert":
            for r in rows:
                if r["id"] == self.payload["id"]:
                    r.update(self.payload)
                    return _Res([r])
            rows.append(dict(self.payload))
            return _Res([self.payload])
        if self.op == "update":
            hit = [r for r in rows if match(r)]
            for r in hit:
                r.update(self.payload)
            return _Res(hit)
        if self.op == "delete":
            self.db.tables[self.name] = [r for r in rows if not match(r)]
            return _Res([])
        out = [dict(r) for r in rows if match(r)]
        if self._order:
            out.sort(key=lambda r: r.get(self._order[0], 0), reverse=self._order[1])
        return _Res(out[: self._limit] if self._limit else out)


class _Bucket:
    def __init__(self, files): self.files = files
    def upload(self, path, data, opts=None): self.files[path] = data
    def download(self, path): return self.files[path]
    def remove(self, paths): [self.files.pop(p, None) for p in paths]
    def create_signed_url(self, path, ttl): return {"signedURL": f"http://signed.test/{path}"}


class FakeSupabase:
    TOKENS = {"tokA": ("user-a", "a@test"), "tokB": ("user-b", "b@test")}

    def __init__(self):
        self.tables, self.files, self.clock = {}, {}, itertools.count(1)
        outer = self

        class _Storage:
            def from_(self, _b): return _Bucket(outer.files)

        class _Auth:
            def get_user(self, token):
                if token not in outer.TOKENS:
                    raise ValueError("bad token")
                uid, email = outer.TOKENS[token]
                return type("R", (), {"user": type("U", (), {"id": uid, "email": email})()})()

        self.storage, self.auth = _Storage(), _Auth()

    def table(self, name): return _Query(self, name)


# ---------- Fake Neo4j (same function contracts as services.graph_store) ----------
class FakeGraph:
    def __init__(self):
        self.docs, self.chunks, self.ents, self.mentions, self.edges = {}, {}, {}, set(), []

    def init_constraints(self): pass

    def write_document(self, doc_id, name, scope, chunks, extractions):
        self.docs[doc_id] = {"name": name, "scope": scope}
        for c in chunks:
            self.chunks[c["id"]] = {"doc_id": doc_id, "page": c["page"]}
            ex = extractions.get(c["id"])
            if not ex:
                continue
            for e in ex.entities:
                self.ents.setdefault(e["id"], dict(e))
                self.mentions.add((c["id"], e["id"]))
            for r in ex.relations:
                self.edges.append({"type": r["type"], "source": r["a"], "target": r["b"],
                                   "doc_id": doc_id, "chunk_id": c["id"]})

    def delete_document(self, doc_id):
        gone = {c for c, v in self.chunks.items() if v["doc_id"] == doc_id}
        touched = {e for c, e in self.mentions if c in gone}
        self.edges = [e for e in self.edges if e["doc_id"] != doc_id]
        self.mentions = {(c, e) for c, e in self.mentions if c not in gone}
        self.chunks = {c: v for c, v in self.chunks.items() if c not in gone}
        self.docs.pop(doc_id, None)
        for e in touched:
            if not any(m[1] == e for m in self.mentions):
                self.ents.pop(e, None)

    def seed_entities(self, question, chunk_ids, scopes):
        ids = {e for c, e in self.mentions if c in chunk_ids and self.ents[e]["scope"] in scopes}
        ids |= {i for i, e in self.ents.items() if e["scope"] in scopes and len(e["norm"]) > 2
                and e["norm"] in question.lower()}
        return list(ids)

    def traverse(self, seeds, doc_ids, scopes, hops, limit=25):
        edges = [e for e in self.edges if e["doc_id"] in doc_ids
                 and self.ents[e["source"]]["scope"] in scopes and self.ents[e["target"]]["scope"] in scopes]
        paths = []
        def walk(node, rels, seen):
            if rels:
                ids = [seen[0]] + [r["_to"] for r in rels]
                paths.append({"nodes": [self._n(i) for i in ids],
                              "rels": [{k: v for k, v in r.items() if k != "_to"} for r in rels]})
            if len(rels) >= hops:
                return
            for e in edges:
                for a, b in ((e["source"], e["target"]), (e["target"], e["source"])):
                    if a == node and b not in seen:
                        walk(b, rels + [dict(e, _to=b)], seen + [b])
        for s in seeds:
            walk(s, [], [s])
        return paths[:limit]

    def _n(self, i): e = self.ents[i]; return {"id": i, "name": e["name"], "type": e["type"]}

    def _visible(self, scopes, doc_ids):
        ok = {c for c, v in self.chunks.items() if v["doc_id"] in doc_ids}
        return {e for c, e in self.mentions if c in ok and self.ents[e]["scope"] in scopes}

    def overview(self, scopes, doc_ids, search, types, limit):
        ids = [i for i in self._visible(scopes, doc_ids)
               if (not search or search.lower() in self.ents[i]["name"].lower())
               and (not types or self.ents[i]["type"] in types)][:limit]
        return {"nodes": [dict(self._n(i), freq=1) for i in ids],
                "edges": [e for e in self.edges if e["source"] in ids and e["target"] in ids and e["doc_id"] in doc_ids]}

    def expand(self, node_id, scopes, doc_ids, limit=30):
        es = [e for e in self.edges if node_id in (e["source"], e["target"]) and e["doc_id"] in doc_ids]
        other = {(e["target"] if e["source"] == node_id else e["source"]) for e in es}
        return {"nodes": [self._n(i) for i in other], "edges": es}

    def node_sources(self, node_id, doc_ids, limit=20):
        return [{"doc_id": self.chunks[c]["doc_id"], "doc_name": self.docs[self.chunks[c]["doc_id"]]["name"],
                 "chunk_id": c, "page": self.chunks[c]["page"]}
                for c, e in self.mentions if e == node_id and self.chunks[c]["doc_id"] in doc_ids]

    def node_info(self, node_id): return self._n(node_id) if node_id in self.ents else None


# ---------- Fake LLM and embedder ----------
class _Msg:
    def __init__(self, content): self.content = content


class FakeLLM:
    def invoke(self, messages):
        import json
        system, human = messages[0][1], messages[1][1]
        low = human.lower()
        if system.startswith("You extract"):
            ents, rels = [], []
            if "metformin" in low: ents.append({"name": "Metformin", "type": "Drug"})
            if "type 2 diabetes" in low: ents.append({"name": "Type 2 Diabetes", "type": "Disease"})
            if "hba1c" in low: ents.append({"name": "HbA1c", "type": "Biomarker"})
            names = {e["name"] for e in ents}
            if {"Metformin", "Type 2 Diabetes"} <= names:
                rels.append({"source": "Metformin", "target": "Type 2 Diabetes", "type": "TREATS"})
            if {"HbA1c", "Type 2 Diabetes"} <= names:
                rels.append({"source": "HbA1c", "target": "Type 2 Diabetes", "type": "ASSOCIATED_WITH"})
            ents.append({"name": "Banana", "type": "Fruit"})  # must be rejected by validation
            return _Msg(json.dumps({"entities": ents, "relations": rels}))
        support = "partial" if "PARTIAL" in human else "full"
        return _Msg("<think>hmm</think>" + json.dumps({"answer": "Metformin treats type 2 diabetes.", "support": support}))


class FakeEmbedder:
    dim = 32

    def _vec(self, text):
        v = [0.0] * self.dim
        for w in text.lower().split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]

    def embed_query(self, t): return self._vec(t)
    def embed_documents(self, ts): return [self._vec(t) for t in ts]


# ---------- Wiring ----------
@pytest.fixture
def env(monkeypatch):
    sb, graph, qd = FakeSupabase(), FakeGraph(), QdrantClient(":memory:")
    for mod in (auth, repo, documents_router, pipeline):
        monkeypatch.setattr(mod, "supabase", lambda: sb)
    monkeypatch.setattr(vector_store, "qdrant", lambda: qd)
    for name in ("init_constraints", "write_document", "delete_document", "seed_entities", "traverse",
                 "overview", "expand", "node_sources", "node_info"):
        monkeypatch.setattr(graph_store, name, getattr(graph, name))
    monkeypatch.setattr(llm, "llm_json", lambda: FakeLLM())
    monkeypatch.setattr(pipeline, "embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(retrieval, "embedder", lambda: FakeEmbedder())
    with TestClient(__import__("app.main", fromlist=["app"]).app) as client:
        yield type("Env", (), {"client": client, "sb": sb, "graph": graph, "qd": qd})()


def H(tok="tokA"):
    return {"Authorization": f"Bearer {tok}"}
