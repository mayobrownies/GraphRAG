import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import current_user
from app.core.config import Settings, get_settings
from app.core.deps import get_document_db, get_document_store
from app.core.errors import InvalidCursor
from app.repositories.document_db import DocumentPage, DocumentRow, Scope
from app.routers import documents
from app.schemas.auth import User

ALICE = "8f14e45f-ceea-4e7a-9f6e-1c2b3d4e5f60"
BOB = "1b2c3d4e-5f60-4a7b-8c9d-0e1f2a3b4c5d"
OWN_ID = "3c9e1a2b-4d5f-4a6b-8c7d-9e0f1a2b3c4d"
GLOBAL_ID = "4d0f2b3c-5e6a-4b7c-9d8e-0f1a2b3c4d5e"
BOBS_ID = "5e1a3c4d-6f7b-4c8d-0e9f-1a2b3c4d5e6f"
PDF = {"file": ("paper.pdf", b"%PDF-1.7\n", "application/pdf")}
EXPIRES = 120


def row(doc_id: str, owner_id: str | None, name: str) -> DocumentRow:
    return DocumentRow(
        id=doc_id,
        owner_id=owner_id,
        is_global=owner_id is None,
        name=name,
        sha256="hash-" + doc_id,
        storage_path=f"{owner_id or 'global'}/{doc_id}.pdf",
        status="ready",
        stage=None,
        error=None,
        created_at="2026-10-21T12:00:00+00:00",
        updated_at="2026-10-21T12:00:00+00:00",
    )


class FakeDB:
    # In-memory stand-in for DocumentDB: own documents plus global ones, and records get_all's arguments
    def __init__(self):
        self.rows = [row(OWN_ID, ALICE, "mine.pdf"), row(GLOBAL_ID, None, "shared.pdf"), row(BOBS_ID, BOB, "bobs.pdf")]
        self.get_all_args = None

    async def get(self, doc_id, user_id, *, scope=Scope.ALL):
        return next((r for r in self.rows if r.id == doc_id and r.owner_id in (user_id, None)), None)

    async def get_all(self, user_id, **kwargs):
        self.get_all_args = kwargs
        if kwargs.get("cursor") == "bad":
            raise InvalidCursor("bad")
        visible = [r for r in self.rows if r.owner_id in (user_id, None)]
        return DocumentPage(items=visible, next_cursor="next-page")


class FakeStore:
    def __init__(self):
        self.signed = []

    async def signed_url(self, path, expires_in):
        self.signed.append((path, expires_in))
        return f"https://signed/{path}?e={expires_in}"


# (method, path, multipart files) for every route in the router
ROUTES = [
    ("POST", "/api/documents", PDF),
    ("GET", "/api/documents", None),
    ("GET", f"/api/documents/{OWN_ID}", None),
    ("POST", f"/api/documents/{OWN_ID}/retry", None),
    ("PUT", f"/api/documents/{OWN_ID}", PDF),
    ("DELETE", f"/api/documents/{OWN_ID}", None),
    ("GET", f"/api/documents/{OWN_ID}/download", None),
]
STUBBED = [route for route in ROUTES if route[0] in ("POST", "PUT", "DELETE")]


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def store():
    return FakeStore()


def make_app(db=None, store=None, signed_in: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(documents.router, prefix="/api")
    # Real auth with a JWKS URL set, so a request without a token is a 401 before any lookup
    settings = Settings(_env_file=None, supabase_jwks_url="https://example/jwks", signed_url_expires_s=EXPIRES)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_document_db] = lambda: db or FakeDB()
    app.dependency_overrides[get_document_store] = lambda: store or FakeStore()
    if signed_in:
        app.dependency_overrides[current_user] = lambda: User(id=ALICE)
    return app


async def send(app: FastAPI, method: str, path: str, files=None, params=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, files=files, params=params)


# Auth and validation


@pytest.mark.parametrize("method,path,files", ROUTES)
async def test_every_route_requires_a_token(method, path, files):
    response = await send(make_app(signed_in=False), method, path, files)
    assert response.status_code == 401


@pytest.mark.parametrize("method,path,files", STUBBED)
async def test_unimplemented_routes_are_501(method, path, files):
    response = await send(make_app(), method, path, files)
    assert response.status_code == 501


@pytest.mark.parametrize("params", [{"limit": 500}, {"limit": 0}, {"scope": "bogus"}, {"status": "done"}])
async def test_list_rejects_bad_query_params(params):
    response = await send(make_app(), "GET", "/api/documents", params=params)
    assert response.status_code == 422


async def test_upload_requires_a_file():
    response = await send(make_app(), "POST", "/api/documents")
    assert response.status_code == 422


# list


async def test_list_returns_public_fields_and_next_cursor(db):
    response = await send(make_app(db), "GET", "/api/documents")
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [OWN_ID, GLOBAL_ID]
    assert body["next_cursor"] == "next-page"
    assert set(body["items"][0]) == {"id", "name", "is_global", "status", "stage", "error", "created_at", "updated_at"}


async def test_list_passes_filters_through(db):
    params = {"scope": "own", "status": "ready", "search": "brca", "limit": 10, "cursor": "abc"}
    await send(make_app(db), "GET", "/api/documents", params=params)
    assert db.get_all_args == {"scope": Scope.OWN, "status": "ready", "search": "brca", "limit": 10, "cursor": "abc"}


async def test_list_bad_cursor_is_400(db):
    response = await send(make_app(db), "GET", "/api/documents", params={"cursor": "bad"})
    assert response.status_code == 400


# get


@pytest.mark.parametrize("doc_id", [OWN_ID, GLOBAL_ID])
async def test_get_returns_visible_documents(db, doc_id):
    response = await send(make_app(db), "GET", f"/api/documents/{doc_id}")
    assert response.status_code == 200
    assert response.json()["id"] == doc_id


@pytest.mark.parametrize("doc_id", [BOBS_ID, "00000000-0000-4000-8000-000000000000", "not-a-uuid"])
async def test_get_hides_whether_a_document_exists(db, doc_id):
    response = await send(make_app(db), "GET", f"/api/documents/{doc_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found"}


# download


async def test_download_signs_the_stored_path(db, store):
    response = await send(make_app(db, store), "GET", f"/api/documents/{GLOBAL_ID}/download")
    assert response.status_code == 200
    assert response.json() == {"url": f"https://signed/global/{GLOBAL_ID}.pdf?e={EXPIRES}", "expires_in": EXPIRES}


async def test_download_of_another_users_document_is_404(db, store):
    response = await send(make_app(db, store), "GET", f"/api/documents/{BOBS_ID}/download")
    assert response.status_code == 404
    assert store.signed == []


# OpenAPI


async def test_openapi_lists_routes_and_models():
    response = await send(make_app(signed_in=False), "GET", "/openapi.json")
    spec = response.json()
    assert set(spec["paths"]) == {
        "/api/documents",
        "/api/documents/{doc_id}",
        "/api/documents/{doc_id}/retry",
        "/api/documents/{doc_id}/download",
    }
    schemas = spec["components"]["schemas"]
    assert {"DocumentRecord", "DocumentList", "SignedUrl"} <= set(schemas)
    # Internal columns must never be part of the public shape
    assert not {"owner_id", "sha256", "storage_path"} & set(schemas["DocumentRecord"]["properties"])
