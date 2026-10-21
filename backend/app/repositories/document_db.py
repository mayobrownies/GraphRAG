"""
Supabase Postgres
Get one document or a page of documents (the user's own plus the global corpus), filtered by scope, status and name
Insert documents, and update status/stage/error as ingestion runs or the file details when a PDF is replaced
Find a duplicate by sha256 for the upload check: the user's own documents first, then global ones they haven't hidden
Hide a global document from one user's workspace (hidden_documents) without affecting other accounts
Profiles: create on first sign-in, read, and set a unique custom username
The PDFs themselves are in Supabase Storage (document_store.py)
The secret key bypasses RLS, so every read starts from _select, which applies the owner and hidden_documents rules
"""

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError
from postgrest.types import CountMethod
from supabase import AsyncClient

DOCUMENTS = "documents"
HIDDEN = "hidden_documents"
PROFILES = "profiles"
MAX_PAGE_SIZE = 100
UNIQUE_VIOLATION = "23505"
STUCK_ERROR = "Processing was interrupted. Please retry."


class DocumentStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Scope(StrEnum):
    ALL = "all"  # the user's own documents plus global ones they haven't hidden
    OWN = "own"
    GLOBAL = "global"


class DuplicateDocument(Exception):
    pass


class UsernameTaken(Exception):
    pass


@dataclass
class DocumentRow:
    id: str
    owner_id: str | None
    is_global: bool
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
    total: int
    limit: int
    offset: int


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


def escape_like(text: str) -> str:
    # Match the search text literally: % and _ are wildcards in ilike
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


DOCUMENT_COLUMNS = columns(DocumentRow)
PROFILE_COLUMNS = columns(Profile)


@dataclass
class DocumentDB:
    client: AsyncClient

    # Reads

    async def get(self, doc_id: str, user_id: str, *, scope: Scope | str = Scope.ALL) -> DocumentRow | None:
        # Use scope "own" before retry, replace or delete, so a global document can't be changed
        if not is_uuid(doc_id):
            return None
        query = await self._select(DOCUMENT_COLUMNS, user_id, scope)
        response = await query.eq("id", doc_id).limit(1).execute()
        return from_row(DocumentRow, response.data[0]) if response.data else None

    async def get_all(
        self,
        user_id: str,
        *,
        scope: Scope | str = Scope.ALL,
        status: DocumentStatus | str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DocumentPage:
        # Newest first, a page at a time; total is the number of matches across all pages
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        if offset < 0:
            raise ValueError("offset must be 0 or more")

        query = await self._select(DOCUMENT_COLUMNS, user_id, scope, count=CountMethod.exact)
        if status is not None:
            query = query.eq("status", DocumentStatus(status))
        if search and search.strip():
            query = query.ilike("name", f"%{escape_like(search.strip())}%")

        # id breaks ties so rows created in the same instant keep a stable order across pages
        response = await (
            query.order("created_at", desc=True).order("id", desc=True).range(offset, offset + limit - 1).execute()
        )
        items = [from_row(DocumentRow, row) for row in response.data]
        return DocumentPage(items=items, total=response.count or 0, limit=limit, offset=offset)

    async def find_duplicate(self, sha256: str, user_id: str | None) -> DocumentRow | None:
        # The user's own copy first, then a global copy they haven't hidden
        # user_id None (the seed script) only checks the global corpus
        scopes = (Scope.OWN, Scope.GLOBAL) if user_id is not None else (Scope.GLOBAL,)
        for scope in scopes:
            query = await self._select(DOCUMENT_COLUMNS, user_id, scope)
            response = await query.eq("sha256", sha256).limit(1).execute()
            if response.data:
                return from_row(DocumentRow, response.data[0])
        return None

    async def ready_ids(self, user_id: str, doc_ids: list[str]) -> list[str]:
        # The subset of doc_ids the user can see and that are 'ready', in the order requested
        requested = [doc_id for doc_id in dict.fromkeys(doc_ids) if is_uuid(doc_id)]
        if not requested:
            return []
        query = await self._select("id", user_id, Scope.ALL)
        response = await query.in_("id", requested).eq("status", DocumentStatus.READY).execute()
        allowed = {row["id"] for row in response.data}
        return [doc_id for doc_id in requested if doc_id in allowed]

    # Writes

    async def create(self, doc_id: str, owner_id: str | None, name: str, sha256: str, storage_path: str) -> DocumentRow:
        # owner_id None means a global corpus document
        row = {
            "id": doc_id,
            "owner_id": owner_id,
            "is_global": owner_id is None,
            "name": name,
            "sha256": sha256,
            "storage_path": storage_path,
            "status": DocumentStatus.PROCESSING,
        }
        response = await self._raise_duplicate(self.client.table(DOCUMENTS).insert(row), sha256)
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
        # One write for every document change. Callers check access (get with scope "own") first
        #   progress:     update(id, stage="Extracting entities")
        #   status:       update(id, "processing" | "ready" | ("failed", error="...")) - a new status clears the
        #                 old stage and error, so a retried document doesn't keep its last failure message
        #   replace file: update(id, "processing", name=..., sha256=...) - the storage path stays the same
        # Returns False if the document doesn't exist
        values: dict[str, Any] = {}
        if status is not None:
            status = DocumentStatus(status)
            if status is DocumentStatus.FAILED and not error:
                raise ValueError("A failed status needs an error message for the user")
            if status is not DocumentStatus.FAILED and error:
                raise ValueError("Only a failed status takes an error message")
            values.update(status=status, stage=stage, error=error)
        elif error:
            raise ValueError("Set an error together with status 'failed'")
        elif stage is not None:
            values["stage"] = stage
        if (name is None) != (sha256 is None):
            raise ValueError("name and sha256 change together when a file is replaced")
        if name is not None:
            values.update(name=name, sha256=sha256)
        if not values:
            raise ValueError("Nothing to update")

        query = self.client.table(DOCUMENTS).update(values).eq("id", doc_id)
        response = await (self._raise_duplicate(query, sha256) if sha256 else query.execute())
        return len(response.data) > 0

    async def delete(self, doc_id: str, owner_id: str) -> bool:
        # Filtering by owner means a global document (owner_id null) is never deleted here
        if not is_uuid(doc_id):
            return False
        response = await self.client.table(DOCUMENTS).delete().eq("id", doc_id).eq("owner_id", owner_id).execute()
        return len(response.data) > 0

    async def hide(self, user_id: str, doc_id: str) -> bool:
        # Only global documents can be hidden; the user's own documents are deleted instead
        if await self.get(doc_id, user_id, scope=Scope.GLOBAL) is None:
            return False
        row = {"user_id": user_id, "document_id": doc_id}
        await self.client.table(HIDDEN).upsert(row, on_conflict="user_id,document_id", ignore_duplicates=True).execute()
        return True

    async def fail_stuck(self) -> int:
        # Run at startup: anything still 'processing' lost its job when the server stopped
        response = await (
            self.client.table(DOCUMENTS)
            .update({"status": DocumentStatus.FAILED, "stage": None, "error": STUCK_ERROR})
            .eq("status", DocumentStatus.PROCESSING)
            .execute()
        )
        return len(response.data)

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
        try:
            response = await self.client.table(PROFILES).update({"username": username}).eq("id", user_id).execute()
        except APIError as error:
            if error.code == UNIQUE_VIOLATION:
                raise UsernameTaken(username) from error
            raise
        return from_row(Profile, response.data[0]) if response.data else None

    # Helpers

    async def _select(self, columns: str, user_id: str | None, scope: Scope | str, *, count: CountMethod | None = None):
        # The one place that decides which documents a user can see; every read starts here
        # user_id None is only allowed for the global scope (the seed script, which has no user)
        scope = Scope(scope)
        if user_id is None and scope is not Scope.GLOBAL:
            raise ValueError("user_id is required unless scope is 'global'")
        # user_id goes into a PostgREST filter string below, so make sure it can't add filters of its own
        if user_id is not None and not is_uuid(user_id):
            raise ValueError("user_id must be a UUID")

        query = self.client.table(DOCUMENTS).select(columns, count=count)
        if user_id is None:
            return query.is_("owner_id", "null")
        if scope is Scope.OWN:
            return query.eq("owner_id", user_id)
        if scope is Scope.GLOBAL:
            query = query.is_("owner_id", "null")
        else:
            query = query.or_(f"owner_id.eq.{user_id},is_global.is.true")
        hidden = await self._hidden_ids(user_id)
        return query.not_.in_("id", sorted(hidden)) if hidden else query

    async def _hidden_ids(self, user_id: str) -> set[str]:
        response = await self.client.table(HIDDEN).select("document_id").eq("user_id", user_id).execute()
        return {row["document_id"] for row in response.data}

    @staticmethod
    async def _raise_duplicate(query, sha256: str):
        # The unique (owner_id, sha256) constraint catches uploads that race past find_duplicate
        try:
            return await query.execute()
        except APIError as error:
            if error.code == UNIQUE_VIOLATION:
                raise DuplicateDocument(sha256) from error
            raise
