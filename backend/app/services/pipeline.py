"""Ingestion pipeline (Figure 1, top half). Ready only after graph and vectors succeed (req 3.5.5)."""
import logging

from .. import repo
from ..config import GLOBAL_SCOPE, get_settings
from ..schema import ValidatedExtraction, validate_extraction
from ..stores import embedder, supabase
from . import graph_store, llm, pdf, vector_store

log = logging.getLogger("pipeline")


def remove_indexes(doc_id: str) -> None:
    graph_store.delete_document(doc_id)
    vector_store.delete_document(doc_id)


def process_document(doc_id: str) -> None:
    s = get_settings()
    doc = repo.get_doc(doc_id)
    if not doc:
        return
    scope = GLOBAL_SCOPE if doc["is_global"] else doc["owner_id"]
    stage = "Starting"
    try:
        stage = "Downloading PDF"
        repo.update(doc_id, status="processing", stage=stage, error=None)
        data = supabase().storage.from_(repo.bucket()).download(doc["storage_path"])

        stage = "Extracting text"
        repo.update(doc_id, stage=stage)
        chunks = pdf.extract_chunks(data, doc_id, s.chunk_size, s.chunk_overlap)

        stage = "Clearing previous index"
        remove_indexes(doc_id)

        extractions: dict[str, ValidatedExtraction] = {}
        for i, c in enumerate(chunks, 1):
            stage = f"Extracting entities ({i}/{len(chunks)})"
            if i == 1 or i % 3 == 0:
                repo.update(doc_id, stage=stage)
            try:
                extractions[c["id"]] = validate_extraction(llm.extract_graph(c["text"]), scope)
            except Exception:
                log.exception("Extraction failed for chunk %s of %s", c["id"], doc_id)
                extractions[c["id"]] = ValidatedExtraction()
        if not any(e.entities for e in extractions.values()):
            raise pdf.IngestError("No entities matching the graph schema could be extracted from this document.")

        stage = "Writing knowledge graph"
        repo.update(doc_id, stage=stage)
        graph_store.write_document(doc_id, doc["name"], scope, chunks, extractions)

        stage = "Generating embeddings"
        repo.update(doc_id, stage=stage)
        vectors = embedder().embed_documents([c["text"] for c in chunks])

        stage = "Writing vector index"
        repo.update(doc_id, stage=stage)
        ents = {cid: [e["id"] for e in ex.entities] for cid, ex in extractions.items()}
        vector_store.upsert(doc["name"], scope, doc["owner_id"], chunks, vectors, ents)

        repo.update(doc_id, status="ready", stage="Ready", error=None)
        log.info("Document %s ready (%d chunks)", doc_id, len(chunks))
    except pdf.IngestError as exc:
        log.warning("Document %s rejected: %s", doc_id, exc)
        _fail(doc_id, str(exc))
    except Exception as exc:
        log.exception("Pipeline failed for %s at stage '%s'", doc_id, stage)
        _fail(doc_id, f"Processing failed during: {stage}. Check backend logs, then retry.")


def _fail(doc_id: str, message: str) -> None:
    try:
        remove_indexes(doc_id)  # never leave partial indexes behind
    except Exception:
        log.exception("Cleanup failed for %s", doc_id)
    repo.update(doc_id, status="failed", stage="Failed", error=message)
