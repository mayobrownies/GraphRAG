from functools import lru_cache

from langchain_ollama import ChatOllama, OllamaEmbeddings
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from supabase import create_client

from .config import get_settings


@lru_cache
def supabase():
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_key)


@lru_cache
def neo4j_driver():
    s = get_settings()
    return GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))


@lru_cache
def qdrant():
    return QdrantClient(url=get_settings().qdrant_url)


@lru_cache
def llm():
    s = get_settings()
    return ChatOllama(model=s.llm_model, base_url=s.ollama_base_url, temperature=0)


@lru_cache
def llm_json():
    s = get_settings()
    return ChatOllama(model=s.llm_model, base_url=s.ollama_base_url, temperature=0, format="json")


@lru_cache
def embedder():
    s = get_settings()
    return OllamaEmbeddings(model=s.embed_model, base_url=s.ollama_base_url)
