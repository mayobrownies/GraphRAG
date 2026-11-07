"""
Supabase Postgres
Library: get one of the user's documents or a page of them, filtered by status and name
Insert documents, and update status/stage/error as ingestion runs or the file details when a PDF is replaced
Find a duplicate by sha256 for the upload check
Groups: named sets of library papers. List (creating "Group 1" for a user with none), create, rename, delete,
add a paper, remove a paper; removing or deleting never touches the paper itself
Profiles: create on first sign-in, read, and set a unique custom username
The PDFs themselves are in Supabase Storage (document_store.py)
The secret key bypasses RLS, so every query filters by owner here
"""

import base64
import json
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError
from supabase import AsyncClient

from app.core.errors import DuplicateDocument, GroupNameTaken, InvalidCursor, UsernameTaken

DOCUMENTS = "documents"
GROUPS = "groups"
GROUP_DOCUMENTS = "group_documents"
PROFILES = "profiles"
MAX_PAGE_SIZE = 100
MAX_GROUP_NAME = 100
DEFAULT_GROUP = "Group 1"
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
STUCK_ERROR = "Processing was interrupted. Please retry."


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass
class DocumentRow:
    id: str
    owner_id: str
    name: str
    sha256: str
    storage_path: str
    status: DocumentStatus
    stage: str | None
    error: str | None
    created_at: str
    updated_at: str

    def __post_init__(self):
        self.status = DocumentStatus(self.status)


@dataclass
class DocumentPage:
    items: list[DocumentRow]
    # Pass back as cursor for the next page; None on the last page
    next_cursor: str | None


@dataclass
class GroupRow:
    id: str
    name: str
    created_at: str
    updated_at: str
    # Library papers in the group, oldest addition first
    document_ids: list[str] = field(default_factory=list)


@dataclass
class Profile:
    id: str
    email: str | None
    username: str | None


def columns(model: type) -> str:
    return ",".join(f.name for f in fields(model))


def from_row(model: type, row: dict[str, Any]):
    # Ignore extra columns so adding one to the table doesn't break reads
    return model(**{f.name: row[f.name] for f in fields(model)})


def is_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
        return True
    except ValueError:
        return False


def check_user(user_id: Any) -> str:
    # Every query filters by this, so anything but a real id is a caller bug
    if not is_uuid(user_id):
        raise ValueError("user_id must be a UUID")
    return str(user_id)


def group_name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= MAX_GROUP_NAME:
        raise ValueError(f"Group name must be 1-{MAX_GROUP_NAME} characters")
    return name


def escape_like(text: str) -> str:
    # Match the search text literally: % and _ are wildcards in ilike
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def encode_cursor(row: "DocumentRow") -> str:
    # The last row's sort key, as UTF-8 JSON in URL-safe base64; opaque to the client
    raw = json.dumps([row.created_at, row.id]).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, str]:
    # Both values go into a PostgREST filter string, so only a real timestamp and UUID get through
    try:
        created_at, doc_id = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
        created_at = datetime.fromisoformat(created_at).isoformat()
    except (ValueError, TypeError) as error:
        raise InvalidCursor(cursor) from error
    if not is_uuid(doc_id):
        raise InvalidCursor(cursor)
    return created_at, str(doc_id)


DOCUMENT_COLUMNS = columns(DocumentRow)
GROUP_COLUMNS = "id,name,created_at,updated_at"
PROFILE_COLUMNS = columns(Profile)


@dataclass
class DocumentDB:
    client: AsyncClient

    # Library reads

    async def get(self, doc_id: str, user_id: str) -> DocumentRow | None:
        if not is_uuid(doc_id):
            return None
        response = await self._documents(DOCUMENT_COLUMNS, user_id).eq("id", doc_id).limit(1).execute()
        return from_row(DocumentRow, response.data[0]) if response.data else None

    async def get_all(
        self,
        user_id: str,
        *,
        status: DocumentStatus | str | None = None,
        search: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> DocumentPage:
        # Newest first, a page at a time: pass next_cursor back as cursor for the following page
        # Keyset pagination, so uploads between requests don't shift or repeat rows
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        after = decode_cursor(cursor) if cursor else None

        query = self._documents(DOCUMENT_COLUMNS, user_id)
        if status is not None:
            query = query.eq("status", DocumentStatus(status))
        if search and search.strip():
            query = query.ilike("name", f"%{escape_like(search.strip())}%")
        if after:
            created_at, doc_id = after
            # Rows that sort after the cursor in (created_at desc, id desc) order
            query = query.or_(f'created_at.lt."{created_at}",and(created_at.eq."{created_at}",id.lt.{doc_id})')

        # id breaks ties so rows created in the same instant keep a stable order across pages
        # One extra row tells us whether there is another page
        response = await query.order("created_at", desc=True).order("id", desc=True).limit(limit + 1).execute()
        rows = [from_row(DocumentRow, row) for row in response.data]
        items = rows[:limit]
        next_cursor = encode_cursor(items[-1]) if len(rows) > limit else None
        return DocumentPage(items=items, next_cursor=next_cursor)

    async def find_duplicate(self, sha256: str, user_id: str) -> DocumentRow | None:
        response = await self._documents(DOCUMENT_COLUMNS, user_id).eq("sha256", sha256).limit(1).execute()
        return from_row(DocumentRow, response.data[0]) if response.data else None

    async def ready_ids(self, user_id: str, doc_ids: list[str]) -> list[str]:
        # The subset of doc_ids the user owns and that are 'ready', in the order requested
        requested = [doc_id for doc_id in dict.fromkeys(doc_ids) if is_uuid(doc_id)]
        if not requested:
            return []
        query = self._documents("id", user_id)
        response = await query.in_("id", requested).eq("status", DocumentStatus.READY).execute()
        allowed = {row["id"] for row in response.data}
        return [doc_id for doc_id in requested if doc_id in allowed]

    # Library writes

    async def create(self, doc_id: str, owner_id: str, name: str, sha256: str, storage_path: str) -> DocumentRow:
        row = {
            "id": doc_id,
            "owner_id": check_user(owner_id),
            "name": name,
            "sha256": sha256,
            "storage_path": storage_path,
            "status": DocumentStatus.PROCESSING,
        }
        response = await self._unique(self.client.table(DOCUMENTS).insert(row), DuplicateDocument(sha256))
        return from_row(DocumentRow, response.data[0])

    async def update(
        self,
        doc_id: str,
        status: DocumentStatus | str | None = None,
        *,
        stage: str | None = None,
        error: str | None = None,
        name: str | None = None,
        sha256: str | None = None,
    ) -> bool:
        # One write for every document change. Callers check ownership (get) first
        #   progress:     update(id, stage="Embedding paper")
        #   status:       update(id, "processing" | "ready" | ("failed", error="...")) - a new status clears the
        #                 old stage and error, so a retried document doesn't keep its last failure message
        #   replace file: update(id, "processing", name=..., sha256=...) - the storage path stays the same
        # Returns False if the document doesn't exist
        status = DocumentStatus(status) if status is not None else None
        if (status is DocumentStatus.FAILED) != bool(error):
            raise ValueError("An error message goes with status 'failed', and only with it")
        if (name is None) != (sha256 is None):
            raise ValueError("name and sha256 change together when a file is replaced")

        values: dict[str, Any] = {}
        if status is not None:
            # A new status replaces stage and error together
            values.update(status=status, stage=stage, error=error)
        elif stage is not None:
            values["stage"] = stage
        if name is not None:
            values.update(name=name, sha256=sha256)
        if not values:
            raise ValueError("Nothing to update")

        query = self.client.table(DOCUMENTS).update(values).eq("id", doc_id)
        response = await (self._unique(query, DuplicateDocument(sha256)) if sha256 else query.execute())
        return len(response.data) > 0

    async def delete(self, doc_id: str, owner_id: str) -> bool:
        # Also removes the paper from every group (group_documents cascades)
        if not is_uuid(doc_id):
            return False
        query = self.client.table(DOCUMENTS).delete().eq("id", doc_id).eq("owner_id", check_user(owner_id))
        response = await query.execute()
        return len(response.data) > 0

    async def fail_stuck(self) -> int:
        # Run at startup: anything still 'processing' lost its job when the server stopped
        response = await (
            self.client.table(DOCUMENTS)
            .update({"status": DocumentStatus.FAILED, "stage": None, "error": STUCK_ERROR})
            .eq("status", DocumentStatus.PROCESSING)
            .execute()
        )
        return len(response.data)

    # Groups

    async def get_groups(self, user_id: str) -> list[GroupRow]:
        # Oldest first. A user with no groups gets an empty "Group 1", so the list is never empty
        groups = await self._groups(user_id)
        if groups:
            return groups
        # Two first requests at once both try; the unique (owner_id, name) lets only one insert through
        row = {"owner_id": user_id, "name": DEFAULT_GROUP}
        await self.client.table(GROUPS).upsert(row, on_conflict="owner_id,name", ignore_duplicates=True).execute()
        return await self._groups(user_id)

    async def get_group(self, group_id: str, user_id: str) -> GroupRow | None:
        if not is_uuid(group_id):
            return None
        groups = await self._groups(user_id, group_id)
        return groups[0] if groups else None

    async def create_group(self, user_id: str, name: str) -> GroupRow:
        name = group_name(name)
        query = self.client.table(GROUPS).insert({"owner_id": check_user(user_id), "name": name})
        response = await self._unique(query, GroupNameTaken(name))
        return from_row(GroupRow, {**response.data[0], "document_ids": []})

    async def rename_group(self, group_id: str, user_id: str, name: str) -> GroupRow | None:
        name = group_name(name)
        if not is_uuid(group_id):
            return None
        query = self.client.table(GROUPS).update({"name": name}).eq("id", group_id).eq("owner_id", check_user(user_id))
        response = await self._unique(query, GroupNameTaken(name))
        return await self.get_group(group_id, user_id) if response.data else None

    async def delete_group(self, group_id: str, user_id: str) -> bool:
        # The papers stay in the library; only their memberships go (group_documents cascades)
        if not is_uuid(group_id):
            return False
        query = self.client.table(GROUPS).delete().eq("id", group_id).eq("owner_id", check_user(user_id))
        response = await query.execute()
        return len(response.data) > 0

    async def add_to_group(self, group_id: str, doc_id: str, user_id: str) -> bool:
        # Adding a paper twice is harmless. False if the group or the paper isn't the user's:
        # the composite foreign keys on (id, owner_id) reject the row
        if not (is_uuid(group_id) and is_uuid(doc_id)):
            return False
        row = {"group_id": group_id, "document_id": doc_id, "owner_id": check_user(user_id)}
        try:
            await self.client.table(GROUP_DOCUMENTS).upsert(
                row, on_conflict="group_id,document_id", ignore_duplicates=True
            ).execute()
        except APIError as error:
            if error.code == FOREIGN_KEY_VIOLATION:
                return False
            raise
        return True

    async def remove_from_group(self, group_id: str, doc_id: str, user_id: str) -> bool:
        # The paper stays in the library. False if it wasn't in the group
        if not (is_uuid(group_id) and is_uuid(doc_id)):
            return False
        response = await (
            self.client.table(GROUP_DOCUMENTS)
            .delete()
            .eq("group_id", group_id)
            .eq("document_id", doc_id)
            .eq("owner_id", check_user(user_id))
            .execute()
        )
        return len(response.data) > 0

    # Profiles

    async def ensure_profile(self, user_id: str, email: str | None) -> Profile:
        row = {"id": user_id, "email": email}
        await self.client.table(PROFILES).upsert(row, on_conflict="id", ignore_duplicates=True).execute()
        profile = await self.get_profile(user_id)
        if profile is None:
            raise LookupError(f"Profile {user_id} was not created")
        return profile

    async def get_profile(self, user_id: str) -> Profile | None:
        response = await self.client.table(PROFILES).select(PROFILE_COLUMNS).eq("id", user_id).limit(1).execute()
        return from_row(Profile, response.data[0]) if response.data else None

    async def set_username(self, user_id: str, username: str) -> Profile | None:
        username = username.strip()
        if not 3 <= len(username) <= 30:
            raise ValueError("Username must be 3-30 characters")
        query = self.client.table(PROFILES).update({"username": username}).eq("id", user_id)
        response = await self._unique(query, UsernameTaken(username))
        return from_row(Profile, response.data[0]) if response.data else None

    # Helpers

    def _documents(self, columns: str, user_id: str):
        # The one place that decides which documents a user can see: only their own
        user_id = check_user(user_id)
        return self.client.table(DOCUMENTS).select(columns).eq("owner_id", user_id)

    async def _groups(self, user_id: str, group_id: str | None = None) -> list[GroupRow]:
        user_id = check_user(user_id)
        query = self.client.table(GROUPS).select(GROUP_COLUMNS).eq("owner_id", user_id)
        members = self.client.table(GROUP_DOCUMENTS).select("group_id,document_id").eq("owner_id", user_id)
        if group_id is not None:
            query = query.eq("id", group_id)
            members = members.eq("group_id", group_id)
        groups = (await query.order("created_at").order("id").execute()).data
        if not groups:
            return []
        document_ids: dict[str, list[str]] = {row["id"]: [] for row in groups}
        for row in (await members.order("added_at").order("document_id").execute()).data:
            # Skip memberships of a group created between the two reads
            if row["group_id"] in document_ids:
                document_ids[row["group_id"]].append(row["document_id"])
        return [from_row(GroupRow, {**row, "document_ids": document_ids[row["id"]]}) for row in groups]

    @staticmethod
    async def _unique(query, error: Exception):
        # Unique constraints catch writes that race past an earlier check: duplicate PDFs, group names, usernames
        try:
            return await query.execute()
        except APIError as api_error:
            if api_error.code == UNIQUE_VIOLATION:
                raise error from api_error
            raise
