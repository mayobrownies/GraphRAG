import pytest

from app import repo
from app.config import get_settings
from .conftest import H, make_pdf

TEXT1 = "Metformin treats type 2 diabetes in adults and is a first line drug"
TEXT2 = "HbA1c is a biomarker associated with type 2 diabetes control and monitoring"


def upload(env, pages=(TEXT1, TEXT2), name="paper.pdf", tok="tokA", **params):
    return env.client.post("/api/documents", params=params, headers=H(tok),
                           files={"file": (name, make_pdf(list(pages)), "application/pdf")})


def ready_doc(env, **kw):
    r = upload(env, **kw)
    assert r.status_code == 202, r.text
    doc = next(d for d in env.client.get("/api/documents", headers=H()).json() if d["id"] == r.json()["id"])
    assert doc["status"] == "ready", doc
    return doc


def test_health_and_auth_required(env):
    assert env.client.get("/health").json() == {"status": "ok"}
    assert env.client.get("/api/documents").status_code == 401
    assert env.client.get("/api/documents", headers=H("nope")).status_code == 401


def test_upload_validation(env):
    r = env.client.post("/api/documents", headers=H(), files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 400
    r = env.client.post("/api/documents", headers=H(), files={"file": ("a.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 400
    get_settings().max_upload_mb = 0
    try:
        assert upload(env).status_code == 413
    finally:
        get_settings().max_upload_mb = 25


def test_ingestion_makes_document_ready_with_pages_and_schema_validation(env):
    doc = ready_doc(env)
    assert doc["name"] == "paper.pdf"
    pts = env.qd.scroll("chunks", limit=10, with_payload=True)[0]
    assert sorted(p.payload["page"] for p in pts) == [1, 2]
    assert all(p.payload["doc_id"] == doc["id"] and p.payload["scope"] == "user-a" for p in pts)
    names = {e["name"] for e in env.graph.ents.values()}
    assert names == {"Metformin", "Type 2 Diabetes", "HbA1c"}  # "Banana/Fruit" rejected
    assert {e["type"] for e in env.graph.edges} == {"TREATS", "ASSOCIATED_WITH"}
    assert all(p.payload["entity_ids"] for p in pts)  # vectors linked to graph entities


def test_empty_and_image_only_pdfs_fail_and_retry_stays_failed(env):
    r = upload(env, pages=("", ""), name="scan.pdf")
    d = env.client.get("/api/documents", headers=H()).json()[0]
    assert d["status"] == "failed" and "image-only" in d["error"]
    assert env.qd.count("chunks").count == 0 and not env.graph.ents
    assert env.client.post(f"/api/documents/{r.json()['id']}/retry", headers=H()).status_code == 202
    assert env.client.get("/api/documents", headers=H()).json()[0]["status"] == "failed"


def test_corrupt_pdf_reports_failure(env):
    r = env.client.post("/api/documents", headers=H(), files={"file": ("bad.pdf", b"%PDF-1.4 garbage", "application/pdf")})
    assert r.status_code == 202
    assert env.client.get("/api/documents", headers=H()).json()[0]["status"] == "failed"


def test_retry_rejected_for_non_failed(env):
    doc = ready_doc(env)
    assert env.client.post(f"/api/documents/{doc['id']}/retry", headers=H()).status_code == 409


def test_duplicate_detection_and_override(env):
    first = ready_doc(env)
    dup = upload(env)
    assert dup.status_code == 409 and dup.json()["detail"]["existing_id"] == first["id"]
    assert len(env.client.get("/api/documents", headers=H()).json()) == 1
    again = upload(env, override=True)
    assert again.status_code == 202 and again.json()["id"] != first["id"]
    docs = env.client.get("/api/documents", headers=H()).json()
    assert [d["id"] for d in docs] == [again.json()["id"]] and docs[0]["status"] == "ready"
    assert env.qd.count("chunks").count == 2 and set(env.graph.docs) == {again.json()["id"]}


def test_hybrid_query_returns_sources_pages_and_graph_path(env):
    doc = ready_doc(env)
    r = env.client.post("/api/query", headers=H(),
                        json={"question": "What does metformin treat?", "doc_ids": [doc["id"]]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"].startswith("Metformin treats") and "<think>" not in body["answer"]
    assert body["support"] == "full" and not body["no_context"]
    assert all({"doc_name", "page", "chunk_id", "snippet", "origin"} <= set(s) for s in body["sources"])
    g = body["graph"]
    assert g["paths"] and any(e["type"] == "TREATS" for e in g["edges"])
    assert any(p["rels"] for p in g["paths"])


def test_two_hop_traversal_reaches_biomarker(env):
    doc = ready_doc(env)
    body = env.client.post("/api/query", headers=H(),
                           json={"question": "metformin", "doc_ids": [doc["id"]]}).json()
    names = {n["name"] for n in body["graph"]["nodes"]}
    assert {"Metformin", "Type 2 Diabetes", "HbA1c"} <= names  # Metformin -> T2D -> HbA1c (2 hops)


def test_standard_mode_has_no_graph(env):
    doc = ready_doc(env)
    body = env.client.post("/api/query", headers=H(),
                           json={"question": "What does metformin treat?", "doc_ids": [doc["id"]], "mode": "standard"}).json()
    assert body["sources"] and body["graph"]["nodes"] == [] and body["mode"] == "standard"


def test_no_usable_context_is_reported_not_fabricated(env):
    doc = ready_doc(env)
    s = get_settings()
    s.min_score = 2.0
    try:
        body = env.client.post("/api/query", headers=H(), json={"question": "zzz qqq", "doc_ids": [doc["id"]], "mode": "standard"}).json()
    finally:
        s.min_score = 0.05
    assert body["no_context"] and body["support"] == "none" and body["sources"] == []
    assert "No usable context" in body["answer"]


def test_partial_support_is_flagged(env):
    doc = ready_doc(env)
    body = env.client.post("/api/query", headers=H(),
                           json={"question": "PARTIAL metformin question", "doc_ids": [doc["id"]]}).json()
    assert body["support"] == "partial" and "insufficient" in body["answer"]


def test_query_requires_ready_selected_documents(env):
    assert env.client.post("/api/query", headers=H(), json={"question": "anything", "doc_ids": []}).status_code == 400
    assert env.client.post("/api/query", headers=H(), json={"question": "anything", "mode": "bogus", "doc_ids": ["x"]}).status_code == 400


def test_benchmark_runs_both_pipelines(env):
    doc = ready_doc(env)
    b = env.client.post("/api/benchmark", headers=H(), json={"question": "What does metformin treat?", "doc_ids": [doc["id"]]}).json()
    assert b["standard"]["mode"] == "standard" and b["graph"]["mode"] == "graph"
    assert b["graph"]["graph"]["nodes"] and not b["standard"]["graph"]["nodes"]
    assert "latency_ms" in b["standard"]


def test_account_isolation(env):
    doc = ready_doc(env)
    assert env.client.get("/api/documents", headers=H("tokB")).json() == []
    assert env.client.delete(f"/api/documents/{doc['id']}", headers=H("tokB")).status_code == 404
    assert env.client.get(f"/api/documents/{doc['id']}/url", headers=H("tokB")).status_code == 404
    assert env.client.post("/api/query", headers=H("tokB"), json={"question": "metformin?", "doc_ids": [doc["id"]]}).status_code == 400
    assert env.client.get(f"/api/graph?doc_ids={doc['id']}", headers=H("tokB")).json() == {"nodes": [], "edges": []}
    # same file uploaded by B is NOT treated as a duplicate of A's document
    assert upload(env, tok="tokB").status_code == 202


def test_global_corpus_readable_by_everyone_but_not_deletable(env):
    ready = ready_doc(env)
    repo.update(ready["id"], is_global=True, owner_id=None)
    for tok in ("tokA", "tokB"):
        docs = env.client.get("/api/documents", headers=H(tok)).json()
        assert docs and docs[0]["is_global"]
    assert env.client.delete(f"/api/documents/{ready['id']}", headers=H("tokB")).status_code == 404
    assert env.client.get(f"/api/documents/{ready['id']}/url", headers=H("tokB")).status_code == 200


def test_delete_removes_graph_vectors_and_storage(env):
    doc = ready_doc(env)
    assert env.client.delete(f"/api/documents/{doc['id']}", headers=H()).status_code == 204
    assert env.qd.count("chunks").count == 0 and not env.graph.ents and not env.graph.edges
    assert not env.sb.files and env.client.get("/api/documents", headers=H()).json() == []


def test_graph_explorer_endpoints(env):
    doc = ready_doc(env)
    ids = doc["id"]
    assert "Disease" in env.client.get("/api/graph/types", headers=H()).json()
    ov = env.client.get(f"/api/graph?doc_ids={ids}", headers=H()).json()
    assert {n["name"] for n in ov["nodes"]} == {"Metformin", "Type 2 Diabetes", "HbA1c"} and ov["edges"]
    f = env.client.get(f"/api/graph?doc_ids={ids}&search=metf&types=Drug", headers=H()).json()
    assert [n["name"] for n in f["nodes"]] == ["Metformin"]
    mid = f["nodes"][0]["id"]
    ex = env.client.get(f"/api/graph/expand/{mid}?doc_ids={ids}", headers=H()).json()
    assert {n["name"] for n in ex["nodes"]} == {"Type 2 Diabetes"}
    node = env.client.get(f"/api/graph/node/{mid}?doc_ids={ids}", headers=H()).json()
    assert node["name"] == "Metformin" and node["sources"][0]["page"] == 1 and node["sources"][0]["snippet"]
    assert env.client.get(f"/api/graph/node/nope?doc_ids={ids}", headers=H()).status_code == 404


def test_source_url(env):
    doc = ready_doc(env)
    assert env.client.get(f"/api/documents/{doc['id']}/url", headers=H()).json()["url"].startswith("http://signed.test/")


def test_username(env):
    assert env.client.put("/api/me/username", headers=H(), json={"username": "x"}).status_code == 400
    assert env.client.put("/api/me/username", headers=H(), json={"username": "dr_caramel"}).status_code == 200
    assert env.client.get("/api/me", headers=H()).json()["username"] == "dr_caramel"


def test_restart_marks_interrupted_documents_failed(env):
    env.sb.table("documents").insert({"id": "d1", "owner_id": "user-a", "is_global": False, "name": "x.pdf",
                                      "status": "processing"}).execute()
    repo.mark_stale_processing()
    d = env.client.get("/api/documents", headers=H()).json()[0]
    assert d["status"] == "failed" and "retry" in d["error"].lower()


def test_state_persists_across_sessions(env):
    ready_doc(env)
    assert len(env.client.get("/api/documents", headers=H()).json()) == 1  # same account, new request
