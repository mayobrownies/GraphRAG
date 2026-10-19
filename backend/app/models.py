"""
Qwen through Ollama: one client for chat (extraction and answer generation) and embeddings (chunks and queries)
Model names and the Ollama URL come from config (OLLAMA_LLM_MODEL, OLLAMA_EMBED_MODEL, OLLAMA_BASE_URL)
The same embedding model must be used for chunks and queries
truncate=False makes Ollama raise on text longer than the embedding model's context, so keep the chunk size below it
Shared data types (DocumentRecord, Response, ...) are in schemas.py
"""

from dataclasses import dataclass

from ollama import AsyncClient


@dataclass
class Models:
    client: AsyncClient
    chat_model: str
    embedding_model: str

    async def chat(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("A non-empty prompt is required.")
        response = await self.client.chat(
            model=self.chat_model,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
        )
        return response.message.content

    async def embed(self, text: str | list[str]) -> list[list[float]]:
        inputs = [text] if isinstance(text, str) else text
        if not inputs or any(not item.strip() for item in inputs):
            raise ValueError("Embedding inputs must contain non-empty text.")
        response = await self.client.embed(
            model=self.embedding_model,
            input=inputs,
            truncate=False,
        )
        return response.embeddings

