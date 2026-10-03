import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ollama import AsyncClient

from app.ollama_models import OllamaModels

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

APP_ENV = os.environ["APP_ENV"]
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ["CORS_ORIGINS"].split(",")
    if origin.strip()
]

OLLAMA_BASE_URL = os.environ["OLLAMA_BASE_URL"]
OLLAMA_LLM_MODEL = os.environ["OLLAMA_LLM_MODEL"]
OLLAMA_EMBED_MODEL = os.environ["OLLAMA_EMBED_MODEL"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncClient(host=OLLAMA_BASE_URL, timeout=120.0) as client:
        app.state.models = OllamaModels(
            client=client,
            chat_model=OLLAMA_LLM_MODEL,
            embedding_model=OLLAMA_EMBED_MODEL,
        )
        yield


app = FastAPI(title="GraphRAG API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"service": "graphrag-api", "version": "0.1.0", "env": APP_ENV}


@app.get("/health")
def health():
    return {"status": "ok"}
