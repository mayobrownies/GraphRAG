"""
FastAPI dependencies that hand routes the repositories created at startup (main.py lifespan stores them on app.state)
Tests replace these with fakes through app.dependency_overrides
"""

from fastapi import Request

from app.repositories.document_db import DocumentDB
from app.repositories.document_store import DocumentStore
from app.repositories.graph_store import GraphStore


def get_document_db(request: Request) -> DocumentDB:
    return request.app.state.document_db


def get_document_store(request: Request) -> DocumentStore:
    return request.app.state.document_store


def get_graph_store(request: Request) -> GraphStore:
    return request.app.state.graph_store
