"""Real LangChain Ollama clients can be constructed with the configured settings (no network call)."""
import app.config  # noqa: F401  (env set in conftest)
from app import stores


def test_ollama_clients_construct():
    stores.llm.cache_clear(); stores.llm_json.cache_clear(); stores.embedder.cache_clear()
    assert stores.llm_json().model == "qwen3.5:0.8b" and stores.llm_json().format == "json"
    assert stores.embedder().model == "nomic-embed-text"
