import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.auth import current_user
from app.core.config import Settings, get_settings
from app.core.deps import get_document_db, get_graph_store
from app.core.errors import GroupNameTaken
from app.repositories.document_db import GroupRow
from app.routers import groups
from app.schemas.auth import User

ALICE = "8f14e45f-ceea-4e7a-9f6e-1c2b3d4e5f60"
BOB = "1b2c3d4e-5f60-4a7b-8c9d-0e1f2a3b4c5d"
MEDICAL = "3c9e1a2b-4d5f-4a6b-8c7d-9e0f1a2b3c4d"
BOBS_GROUP = "5e1a3c4d-6f7b-4c8d-0e9f-1a2b3c4d5e6f"
READY = "6f2b4d5e-7a8c-4d9e-8f0a-2b3c4d5e6f70"
PROCESSING = "7a3c5e6f-8b9d-4e0f-9a1b-3c4d5e6f7081"
BOBS_PAPER = "8b4d6f7a-9c0e-4f1a-8b2c-4d5e6f708192"
STAMP = "2026-10-21T12:00:00+00:00"


class FakeDB:
    # In-memory stand-in for the group and library parts of DocumentDB, with the same ownership rules
    def __init__(self):
        self.groups = {MEDICAL: [ALICE, "Medical", [READY, PROCESSING]], BOBS_GROUP: [BOB, "Bob's", [BOBS_PAPER]]}
        self.papers = {READY: (ALICE, "ready"), PROCESSING: (ALICE, "processing"), BOBS_PAPER: (BOB, "ready")}

    def _row(self, group_id):
        owner, name, doc_ids = self.groups[group_id]
        return GroupRow(group_id, name, STAMP, STAMP, list(doc_ids))

    def _taken(self, user_id, name, skip=None):
        if any(g[0] == user_id and g[1] == name for gid, g in self.groups.items() if gid != skip):
            raise GroupNameTaken(name)

    async def get_groups(self, user_id):
        return [self._row(gid) for gid, g in self.groups.items() if g[0] == user_id]

    async def get_group(self, group_id, user_id):
        group = self.groups.get(group_id)
        return self._row(group_id) if group and group[0] == user_id else None

    async def create_group(self, user_id, name):
        self._taken(user_id, name)
        group_id = f"00000000-0000-4000-8000-{len(self.groups):012d}"
        self.groups[group_id] = [user_id, name, []]
        return self._row(group_id)

    async def rename_group(self, group_id, user_id, name):
        if not await self.get_group(group_id, user_id):
            return None
        self._taken(user_id, name, skip=group_id)
        self.groups[group_id][1] = name
        return self._row(group_id)

    async def delete_group(self, group_id, user_id):
        if not await self.get_group(group_id, user_id):
            return False
        del self.groups[group_id]
        return True

    async def add_to_group(self, group_id, doc_id, user_id):
        paper = self.papers.get(doc_id)
        if not await self.get_group(group_id, user_id) or not paper or paper[0] != user_id:
            return False
        if doc_id not in self.groups[group_id][2]:
            self.groups[group_id][2].append(doc_id)
        return True

    async def remove_from_group(self, group_id, doc_id, user_id):
        doc_ids = self.groups[group_id][2]
        if doc_id in doc_ids:
            doc_ids.remove(doc_id)
            return True
        return False

    async def ready_ids(self, user_id, doc_ids):
        return [d for d in doc_ids if self.papers.get(d) == (user_id, "ready")]


class FakeGraph:
    def __init__(self):
        self.calls = []

    async def graph(self, doc_ids, text="", limit=50, per_paper=5):
        self.calls.append((doc_ids, text, limit, per_paper))
        nodes = [{"doc_id": doc_id, "name": f"paper {doc_id}"} for doc_id in doc_ids]
        return {"nodes": nodes, "edges": []}


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
def graph():
    return FakeGraph()


def make_app(db=None, graph=None, signed_in: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(groups.router, prefix="/api")
    # Real auth with a JWKS URL set, so a request without a token is a 401 before any lookup
    settings = Settings(_env_file=None, supabase_jwks_url="https://example/jwks")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_document_db] = lambda: db or FakeDB()
    app.dependency_overrides[get_graph_store] = lambda: graph or FakeGraph()
    if signed_in:
        app.dependency_overrides[current_user] = lambda: User(id=ALICE)
    return app


async def send(app: FastAPI, method: str, path: str, json=None, params=None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, json=json, params=params)


ROUTES = [
    ("GET", "/api/groups"),
    ("POST", "/api/groups"),
    ("PATCH", f"/api/groups/{MEDICAL}"),
    ("DELETE", f"/api/groups/{MEDICAL}"),
    ("PUT", f"/api/groups/{MEDICAL}/documents/{READY}"),
    ("DELETE", f"/api/groups/{MEDICAL}/documents/{READY}"),
    ("GET", f"/api/groups/{MEDICAL}/graph"),
]


@pytest.mark.parametrize("method,path", ROUTES)
async def test_every_route_requires_a_token(method, path):
    response = await send(make_app(signed_in=False), method, path, json={"name": "x"})
    assert response.status_code == 401


async def test_list_shows_only_own_groups_with_their_papers(db):
    response = await send(make_app(db), "GET", "/api/groups")
    assert response.status_code == 200
    assert [(g["id"], g["name"], g["document_ids"]) for g in response.json()] == [
        (MEDICAL, "Medical", [READY, PROCESSING])
    ]


async def test_create_trims_the_name(db):
    response = await send(make_app(db), "POST", "/api/groups", json={"name": "  AI research "})
    assert response.status_code == 201
    assert response.json()["name"] == "AI research" and response.json()["document_ids"] == []


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
async def test_create_rejects_bad_names(db, name):
    response = await send(make_app(db), "POST", "/api/groups", json={"name": name})
    assert response.status_code == 422


async def test_duplicate_name_is_409(db):
    created = await send(make_app(db), "POST", "/api/groups", json={"name": "Medical"})
    assert created.status_code == 409
    await send(make_app(db), "POST", "/api/groups", json={"name": "AI"})
    renamed = await send(make_app(db), "PATCH", f"/api/groups/{MEDICAL}", json={"name": "AI"})
    assert renamed.status_code == 409


async def test_rename(db):
    response = await send(make_app(db), "PATCH", f"/api/groups/{MEDICAL}", json={"name": "Oncology"})
    assert response.status_code == 200 and response.json()["name"] == "Oncology"


@pytest.mark.parametrize(
    "method,path,json",
    [
        ("PATCH", f"/api/groups/{BOBS_GROUP}", {"name": "Mine"}),
        ("DELETE", f"/api/groups/{BOBS_GROUP}", None),
        ("PUT", f"/api/groups/{BOBS_GROUP}/documents/{READY}", None),
        ("DELETE", f"/api/groups/{BOBS_GROUP}/documents/{BOBS_PAPER}", None),
        ("GET", f"/api/groups/{BOBS_GROUP}/graph", None),
        ("PATCH", "/api/groups/not-a-uuid", {"name": "Mine"}),
    ],
)
async def test_other_users_groups_are_404(db, method, path, json):
    response = await send(make_app(db), method, path, json=json)
    assert response.status_code == 404
    assert db.groups[BOBS_GROUP] == [BOB, "Bob's", [BOBS_PAPER]]


async def test_delete_group(db):
    response = await send(make_app(db), "DELETE", f"/api/groups/{MEDICAL}")
    assert response.status_code == 204
    assert MEDICAL not in db.groups


async def test_add_and_remove_papers(db):
    app = make_app(db)
    removed = await send(app, "DELETE", f"/api/groups/{MEDICAL}/documents/{READY}")
    assert removed.status_code == 200 and removed.json()["document_ids"] == [PROCESSING]
    added = await send(app, "PUT", f"/api/groups/{MEDICAL}/documents/{READY}")
    assert added.status_code == 200 and added.json()["document_ids"] == [PROCESSING, READY]
    # Removing a paper that isn't in the group is harmless
    again = await send(app, "DELETE", f"/api/groups/{MEDICAL}/documents/{BOBS_PAPER}")
    assert again.status_code == 200 and again.json()["document_ids"] == [PROCESSING, READY]


async def test_another_users_paper_cannot_be_added(db):
    response = await send(make_app(db), "PUT", f"/api/groups/{MEDICAL}/documents/{BOBS_PAPER}")
    assert response.status_code == 404
    assert db.groups[MEDICAL][2] == [READY, PROCESSING]


async def test_graph_reads_only_the_groups_ready_papers(db, graph):
    params = {"search": "brca", "limit": 10, "per_paper": 3}
    response = await send(make_app(db, graph), "GET", f"/api/groups/{MEDICAL}/graph", params=params)
    assert response.status_code == 200
    assert response.json() == {"nodes": [{"doc_id": READY, "name": f"paper {READY}"}], "edges": []}
    assert graph.calls == [([READY], "brca", 10, 3)]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"per_paper": 0}, {"search": "x" * 201}])
async def test_graph_rejects_bad_query_params(db, graph, params):
    response = await send(make_app(db, graph), "GET", f"/api/groups/{MEDICAL}/graph", params=params)
    assert response.status_code == 422
    assert graph.calls == []
