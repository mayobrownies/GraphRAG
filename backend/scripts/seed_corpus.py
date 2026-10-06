"""Index the global medical corpus (PDFs in ../corpus) so every account can query it.

Usage (inside the backend container or a configured venv):
    python -m scripts.seed_corpus /path/to/corpus
"""
import hashlib
import sys
import uuid
from pathlib import Path

from app import repo
from app.services import graph_store, pipeline, vector_store
from app.stores import supabase


def main(folder: str) -> None:
    graph_store.init_constraints()
    vector_store.ensure_collection()
    for pdf_path in sorted(Path(folder).glob("*.pdf")):
        data = pdf_path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        existing = [d for d in repo.list_docs("") if d["is_global"] and d["sha256"] == sha]
        if existing:
            print(f"skip (already indexed): {pdf_path.name}")
            continue
        doc_id = str(uuid.uuid4())
        path = f"global/{doc_id}.pdf"
        supabase().storage.from_(repo.bucket()).upload(path, data, {"content-type": "application/pdf"})
        repo.insert({"id": doc_id, "owner_id": None, "is_global": True, "name": pdf_path.name, "sha256": sha,
                     "storage_path": path, "status": "processing", "stage": "Queued"})
        pipeline.process_document(doc_id)
        print(f"indexed: {pdf_path.name} -> {repo.get_doc(doc_id)['status']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../corpus")
