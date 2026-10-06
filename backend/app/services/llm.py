"""LLM helpers: JSON extraction and grounded generation with Qwen through Ollama."""
import json
import re

from ..schema import NODE_TYPES, REL_TYPES
from ..stores import llm, llm_json

_THINK = re.compile(r"<think>.*?</think>", re.S)

EXTRACT_SYSTEM = (
    "You extract a knowledge graph from medical text.\n"
    "Allowed entity types: __NODES__\n"
    "Allowed relationship types: __RELS__\n"
    'Return ONLY JSON: {"entities":[{"name":"...","type":"..."}],'
    '"relations":[{"source":"...","target":"...","type":"..."}]}\n'
    "Use only the allowed types. Use entity names as written in the text. Do not invent facts."
).replace("__NODES__", ", ".join(NODE_TYPES)).replace("__RELS__", ", ".join(REL_TYPES))

ANSWER_SYSTEM = (
    "You answer questions using ONLY the provided context. If the context does not "
    "fully answer the question, say what is supported and state that the evidence is insufficient. "
    "Never use outside knowledge. Return ONLY JSON: "
    '{"answer":"...","support":"full"} where support is "full" when the context completely '
    'answers the question or "partial" when it only partly does.'
)


def clean(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def parse_json(text: str) -> dict | None:
    text = clean(text)
    for candidate in (text, *re.findall(r"\{.*\}", text, re.S)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def extract_graph(chunk_text: str) -> dict:
    msg = llm_json().invoke([("system", EXTRACT_SYSTEM), ("human", f"Text:\n{chunk_text}")])
    return parse_json(msg.content) or {"entities": [], "relations": []}


def generate_answer(question: str, passages: list[str], graph_lines: list[str]) -> dict:
    ctx = "PASSAGES:\n" + "\n---\n".join(passages)
    if graph_lines:
        ctx += "\n\nGRAPH RELATIONSHIPS:\n" + "\n".join(graph_lines)
    msg = llm_json().invoke([("system", ANSWER_SYSTEM), ("human", f"{ctx}\n\nQUESTION: {question}")])
    obj = parse_json(msg.content)
    if obj and obj.get("answer"):
        support = "partial" if str(obj.get("support", "")).lower() == "partial" else "full"
        return {"answer": str(obj["answer"]).strip(), "support": support}
    # Conservative fallback: unparsable output is flagged as partial support.
    return {"answer": clean(msg.content) or "No answer could be generated.", "support": "partial"}
