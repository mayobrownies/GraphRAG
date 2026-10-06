"""Query orchestration and response generation (req 3.7)."""
import time

from . import llm, retrieval

NO_CONTEXT_MESSAGE = "No usable context was found in the selected documents for this question."


def run_query(user_id: str, question: str, doc_ids: list[str], mode: str = "graph") -> dict:
    t0 = time.perf_counter()
    ret = (retrieval.hybrid_retrieve if mode == "graph" else retrieval.standard_retrieve)(user_id, question, doc_ids)
    sources = ret["sources"]
    if not sources:  # req 3.6.5, 3.7.4: never fabricate an answer
        return {"mode": mode, "answer": NO_CONTEXT_MESSAGE, "support": "none", "no_context": True,
                "sources": [], "graph": ret["graph"], "latency_ms": int((time.perf_counter() - t0) * 1000)}
    gen = llm.generate_answer(question, [f"[{s['doc_name']} p.{s['page']}] {s['text']}" for s in sources],
                              ret["graph_lines"])
    answer = gen["answer"]
    if gen["support"] == "partial":  # req 3.7.5
        answer += "\n\nNote: the available evidence is insufficient to answer this question completely."
    return {"mode": mode, "answer": answer, "support": gen["support"], "no_context": False,
            "sources": [{k: v for k, v in s.items() if k != "text"} | {"snippet": s["text"][:300]} for s in sources],
            "graph": ret["graph"], "latency_ms": int((time.perf_counter() - t0) * 1000)}
