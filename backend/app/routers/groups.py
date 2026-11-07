"""
Groups: named sets of the user's library papers, managed from the graph explorer
list (never empty: a user with no groups gets "Group 1"), create, rename, delete
add a library paper to a group, or remove it from the group (the paper stays in the library)
the group's paper graph: its 'ready' papers and their strongest ASSOCIATED_WITH links
Deleting a paper from the library (documents router) removes it from every group
One 404 for unknown, invalid and other users' ids, so nothing reveals that a group or paper exists
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import current_user
from app.core.deps import get_document_db, get_graph_store
from app.core.errors import GroupNameTaken
from app.repositories.document_db import DocumentDB, GroupRow
from app.repositories.graph_store import GraphStore
from app.schemas.auth import User
from app.schemas.groups import GroupInput, GroupRecord, PaperGraph

router = APIRouter(prefix="/groups", tags=["groups"])

NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"description": "Missing, or not this user's"}}
NAME_TAKEN = {status.HTTP_409_CONFLICT: {"description": "The user already has a group with this name"}}


def name_taken(error: GroupNameTaken) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "You already have a group with that name")


async def find_group(db: DocumentDB, group_id: str, user: User) -> GroupRow:
    group = await db.get_group(group_id, user.id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


@router.get("")
async def list_groups(user: User = Depends(current_user), db: DocumentDB = Depends(get_document_db)) -> list[GroupRecord]:
    return [GroupRecord.model_validate(group) for group in await db.get_groups(user.id)]


@router.post("", status_code=status.HTTP_201_CREATED, responses=NAME_TAKEN)
async def create_group(
    body: GroupInput,
    user: User = Depends(current_user),
    db: DocumentDB = Depends(get_document_db),
) -> GroupRecord:
    try:
        return GroupRecord.model_validate(await db.create_group(user.id, body.name))
    except GroupNameTaken as error:
        raise name_taken(error) from error


@router.patch("/{group_id}", responses={**NOT_FOUND, **NAME_TAKEN})
async def rename_group(
    group_id: str,
    body: GroupInput,
    user: User = Depends(current_user),
    db: DocumentDB = Depends(get_document_db),
) -> GroupRecord:
    try:
        group = await db.rename_group(group_id, user.id, body.name)
    except GroupNameTaken as error:
        raise name_taken(error) from error
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return GroupRecord.model_validate(group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
async def delete_group(
    group_id: str,
    user: User = Depends(current_user),
    db: DocumentDB = Depends(get_document_db),
) -> None:
    # The papers stay in the library. Deleting the last group is allowed; the next list recreates "Group 1"
    if not await db.delete_group(group_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")


@router.put("/{group_id}/documents/{doc_id}", responses=NOT_FOUND)
async def add_document(
    group_id: str,
    doc_id: str,
    user: User = Depends(current_user),
    db: DocumentDB = Depends(get_document_db),
) -> GroupRecord:
    # Any library paper can be added; only 'ready' ones appear in the graph and in answers
    if not await db.add_to_group(group_id, doc_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group or document not found")
    return GroupRecord.model_validate(await find_group(db, group_id, user))


@router.delete("/{group_id}/documents/{doc_id}", responses=NOT_FOUND)
async def remove_document(
    group_id: str,
    doc_id: str,
    user: User = Depends(current_user),
    db: DocumentDB = Depends(get_document_db),
) -> GroupRecord:
    # Removing a paper that isn't in the group is harmless; the paper itself is never deleted here
    await find_group(db, group_id, user)
    await db.remove_from_group(group_id, doc_id, user.id)
    return GroupRecord.model_validate(await find_group(db, group_id, user))


@router.get("/{group_id}/graph", responses=NOT_FOUND)
async def group_graph(
    group_id: str,
    # Case-insensitive part of a paper name; empty shows every paper
    search: str = Query("", max_length=200),
    limit: int = Query(50, ge=1, le=200),
    # How many of each paper's strongest links to keep
    per_paper: int = Query(5, ge=1, le=200),
    user: User = Depends(current_user),
    db: DocumentDB = Depends(get_document_db),
    graph: GraphStore = Depends(get_graph_store),
) -> PaperGraph:
    group = await find_group(db, group_id, user)
    # graph_store trusts the ids it gets, so pass only the user's 'ready' papers
    doc_ids = await db.ready_ids(user.id, group.document_ids)
    return PaperGraph.model_validate(await graph.graph(doc_ids, search, limit=limit, per_paper=per_paper))
