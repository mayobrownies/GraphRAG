"""
Group and paper-graph API shapes
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.repositories.document_db import MAX_GROUP_NAME

GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_GROUP_NAME)]


class GroupRecord(BaseModel):
    # Built straight from a GroupRow: GroupRecord.model_validate(row)
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    # Library papers in the group, oldest addition first; any status, the graph shows only 'ready' ones
    document_ids: list[str]
    created_at: datetime
    updated_at: datetime


class GroupInput(BaseModel):
    name: GroupName


class PaperNode(BaseModel):
    doc_id: str
    name: str


class PaperEdge(BaseModel):
    # Undirected: source and target are only the stored direction
    source: str
    target: str
    # Cosine similarity of the two papers' embeddings, in [-1, 1]
    weight: float


class PaperGraph(BaseModel):
    nodes: list[PaperNode]
    edges: list[PaperEdge]
