from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import repo
from ..auth import User, current_user
from ..services import qa

router = APIRouter(prefix="/api", tags=["query"])


class QueryIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    doc_ids: list[str] = []
    mode: str = "graph"  # "graph" or "standard"


class BenchmarkIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    doc_ids: list[str] = []


def _authorized_ids(user: User, requested: list[str]) -> list[str]:
    docs = repo.accessible_ready(user.id, requested or None)
    if not docs:
        raise HTTPException(400, "Select at least one ready document.")
    return [d["id"] for d in docs]


@router.post("/query")
def query(body: QueryIn, user: User = Depends(current_user)):
    if body.mode not in ("graph", "standard"):
        raise HTTPException(400, "mode must be 'graph' or 'standard'")
    return qa.run_query(user.id, body.question, _authorized_ids(user, body.doc_ids), body.mode)


@router.post("/benchmark")
def benchmark(body: BenchmarkIn, user: User = Depends(current_user)):
    ids = _authorized_ids(user, body.doc_ids)
    return {"standard": qa.run_query(user.id, body.question, ids, "standard"),
            "graph": qa.run_query(user.id, body.question, ids, "graph")}
