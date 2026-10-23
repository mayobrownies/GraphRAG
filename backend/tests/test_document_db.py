import base64
import os
from datetime import datetime
from uuid import uuid4

import pytest
from supabase import acreate_client

from app.repositories.document_db import (
    DocumentDB,
    DocumentRow,
    DocumentStatus,
    DuplicateDocument,
    InvalidCursor,
    UsernameTaken,
    decode_cursor,
    encode_cursor,
)

# There is no in-memory Supabase, so the database tests need a dev project with supabase/schema.sql applied
# Use a dev project only: fail_stuck marks every 'processing' document in it as 'failed'
SUPABASE_TEST_URL = os.getenv("SUPABASE_TEST_URL")
SUPABASE_TEST_KEY = os.getenv("SUPABASE_TEST_KEY")
needs_supabase = pytest.mark.skipif(
    not (SUPABASE_TEST_URL and SUPABASE_TEST_KEY),
    reason="set SUPABASE_TEST_URL and SUPABASE_TEST_KEY (secret key) to run",
)


# Validation runs before any query, so these don't need a client


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"status": "failed"},
        {"status": "ready", "error": "boom"},
        {"error": "boom"},
        {"name": "a.pdf"},
        {"sha256": "abc"},
        {"status": "done"},
    ],
)
async def test_update_rejects_invalid_changes(kwargs):
    with pytest.raises(ValueError):
        await DocumentDB(client=None).update(str(uuid4()), **kwargs)


@pytest.mark.parametrize("kwargs", [{"scope": "everyone"}, {"limit": 0}, {"limit": 101}, {"cursor": "not-a-cursor"}])
async def test_get_all_rejects_invalid_arguments(kwargs):
    with pytest.raises(ValueError):
        await DocumentDB(client=None).get_all(str(uuid4()), **kwargs)


def test_cursor_round_trips():
    doc_id = str(uuid4())
    row = DocumentRow(doc_id, None, True, "a.pdf", "h", "p", "ready", None, None,
                      "2026-10-21T12:00:00.123456+00:00", "2026-10-21T12:00:00.123456+00:00")
    assert decode_cursor(encode_cursor(row)) == ("2026-10-21T12:00:00.123456+00:00", doc_id)


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


@pytest.mark.parametrize(
    "cursor",
    [
        "%%%",
        "é",
        b64("not json"),
        b64('{"a": 1}'),
        b64('["2026-10-21T12:00:00+00:00"]'),
        b64('[1, "8f14e45f-ceea-4e7a-9f6e-1c2b3d4e5f60"]'),
        # Filter injection attempts must not survive decoding
        b64('["2026-10-21T12:00:00+00:00,owner_id.is.null", "8f14e45f-ceea-4e7a-9f6e-1c2b3d4e5f60"]'),
        b64('["2026-10-21T12:00:00+00:00", "x),is_global.is.true"]'),
    ],
)
def test_bad_cursors_are_rejected(cursor):
    with pytest.raises(InvalidCursor):
        decode_cursor(cursor)


async def test_user_id_must_be_a_uuid():
    # It goes into a PostgREST filter string, so anything else could add filters
    with pytest.raises(ValueError):
        await DocumentDB(client=None).get_all("x,is_global.is.false")


async def test_user_id_required_outside_global_scope():
    with pytest.raises(ValueError):
        await DocumentDB(client=None).get_all(None, scope="own")


@pytest.mark.parametrize("username", ["ab", "x" * 31, "   "])
async def test_set_username_checks_length(username):
    with pytest.raises(ValueError):
        await DocumentDB(client=None).set_username(str(uuid4()), username)


# Database behaviour


@pytest.fixture
async def client():
    return await acreate_client(SUPABASE_TEST_URL, SUPABASE_TEST_KEY)


@pytest.fixture
def db(client):
    return DocumentDB(client=client)


@pytest.fixture
async def users(client):
    # owner_id references auth.users, so tests need real users; deleting them cascades to their rows
    ids = []
    for _ in range(2):
        response = await client.auth.admin.create_user({"email": f"test-{uuid4()}@example.com", "email_confirm": True})
        ids.append(response.user.id)
    yield ids
    for user_id in ids:
        await client.auth.admin.delete_user(user_id)


@pytest.fixture
async def global_ids(client):
    # Global documents have no owner to cascade from, so delete them explicitly
    ids = []
    yield ids
    if ids:
        await client.table("documents").delete().in_("id", ids).execute()


async def add(db, owner_id, *, sha256=None, name="paper.pdf", global_ids=None):
    doc_id = str(uuid4())
    document = await db.create(doc_id, owner_id, name, sha256 or uuid4().hex, f"{owner_id or 'global'}/{doc_id}.pdf")
    if owner_id is None:
        global_ids.append(doc_id)
    return document


@needs_supabase
async def test_users_only_see_their_own_documents(db, users):
    alice, bob = users
    document = await add(db, bob)
    assert await db.get(document.id, alice) is None
    assert await db.get(document.id, bob, scope="own") == document
    assert document.id not in [d.id for d in (await db.get_all(alice)).items]


@needs_supabase
async def test_hiding_a_global_document_only_affects_that_user(db, users, global_ids):
    alice, bob = users
    document = await add(db, None, global_ids=global_ids)
    assert await db.get(document.id, alice) is not None
    assert await db.hide(alice, document.id) is True
    assert await db.hide(alice, document.id) is True  # hiding twice is harmless
    assert await db.get(document.id, alice) is None
    assert await db.get(document.id, bob) is not None


@needs_supabase
async def test_hide_rejects_own_documents(db, users):
    document = await add(db, users[0])
    assert await db.hide(users[0], document.id) is False


@needs_supabase
async def test_get_all_filters_and_paginates(db, users):
    alice = users[0]
    for index in range(3):
        await add(db, alice, name=f"brca1_{index}.pdf")
    other = await add(db, alice, name="statins.pdf")
    await db.update(other.id, "ready")

    first = await db.get_all(alice, scope="own", search="brca1_", limit=2)
    second = await db.get_all(alice, scope="own", search="brca1_", limit=2, cursor=first.next_cursor)
    assert len(first.items) == 2 and first.next_cursor
    assert len(second.items) == 1 and second.next_cursor is None
    assert not {d.id for d in first.items} & {d.id for d in second.items}

    ready = await db.get_all(alice, scope="own", status="ready")
    assert [d.id for d in ready.items] == [other.id]
    assert ready.next_cursor is None


@needs_supabase
async def test_cursor_pages_keep_the_scope_filter(db, users, global_ids):
    # Scope "all" already sends an or= filter; the cursor adds a second one, and both must apply
    alice, bob = users
    tag = uuid4().hex[:8]
    mine = [await add(db, alice, name=f"{tag}_{i}.pdf") for i in range(3)]
    shared = await add(db, None, name=f"{tag}_global.pdf", global_ids=global_ids)
    await add(db, bob, name=f"{tag}_bob.pdf")

    seen, cursor = [], None
    while True:
        page = await db.get_all(alice, search=tag, limit=1, cursor=cursor)
        seen += [d.id for d in page.items]
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    # Every visible document exactly once, newest first, and never bob's
    expected = sorted(mine + [shared], key=lambda d: (datetime.fromisoformat(d.created_at), d.id), reverse=True)
    assert seen == [d.id for d in expected]


@needs_supabase
async def test_find_duplicate_checks_own_then_visible_global(db, users, global_ids):
    alice, bob = users
    own = await add(db, alice)
    shared = await add(db, None, global_ids=global_ids)

    assert (await db.find_duplicate(own.sha256, alice)).id == own.id
    assert await db.find_duplicate(own.sha256, bob) is None
    assert (await db.find_duplicate(shared.sha256, alice)).id == shared.id
    assert (await db.find_duplicate(shared.sha256, None)).id == shared.id

    await db.hide(alice, shared.id)
    assert await db.find_duplicate(shared.sha256, alice) is None


@needs_supabase
async def test_same_file_twice_raises_duplicate(db, users):
    document = await add(db, users[0])
    with pytest.raises(DuplicateDocument):
        await add(db, users[0], sha256=document.sha256)
    # A different user can upload the same file
    await add(db, users[1], sha256=document.sha256)


@needs_supabase
async def test_ready_ids_keeps_only_visible_ready_documents(db, users):
    alice, bob = users
    ready = await add(db, alice)
    processing = await add(db, alice)
    failed = await add(db, alice)
    bobs = await add(db, bob)
    await db.update(ready.id, "ready")
    await db.update(failed.id, "failed", error="Unreadable PDF")
    await db.update(bobs.id, "ready")

    requested = [bobs.id, processing.id, ready.id, failed.id, "not-a-uuid", ready.id]
    assert await db.ready_ids(alice, requested) == [ready.id]


@needs_supabase
async def test_update_status_clears_old_stage_and_error(db, users):
    document = await add(db, users[0])
    assert await db.update(document.id, stage="Extracting entities") is True
    await db.update(document.id, "failed", error="Unreadable PDF")
    failed = await db.get(document.id, users[0])
    assert failed.status is DocumentStatus.FAILED and failed.error == "Unreadable PDF" and failed.stage is None
    assert failed.updated_at != document.updated_at

    await db.update(document.id, "processing", stage="Retrying")
    retried = await db.get(document.id, users[0])
    assert retried.status is DocumentStatus.PROCESSING and retried.error is None and retried.stage == "Retrying"


@needs_supabase
async def test_update_replaces_file_details(db, users):
    alice = users[0]
    document = await add(db, alice)
    other = await add(db, alice)
    assert await db.update(document.id, "processing", name="v2.pdf", sha256="new-hash") is True
    assert (await db.get(document.id, alice)).name == "v2.pdf"
    with pytest.raises(DuplicateDocument):
        await db.update(document.id, "processing", name="copy.pdf", sha256=other.sha256)


@needs_supabase
async def test_delete_only_removes_own_documents(db, users, global_ids):
    alice, bob = users
    bobs = await add(db, bob)
    shared = await add(db, None, global_ids=global_ids)
    assert await db.delete(bobs.id, alice) is False
    assert await db.delete(shared.id, alice) is False
    assert await db.delete(bobs.id, bob) is True
    assert await db.get(bobs.id, bob) is None


@needs_supabase
async def test_fail_stuck_marks_processing_as_failed(db, users):
    document = await add(db, users[0])
    assert await db.fail_stuck() >= 1
    stuck = await db.get(document.id, users[0])
    assert stuck.status is DocumentStatus.FAILED and stuck.error


@needs_supabase
async def test_profiles(db, users):
    alice, bob = users
    first = await db.ensure_profile(alice, "alice@example.com")
    assert await db.ensure_profile(alice, "alice@example.com") == first
    assert first.username is None

    name = f"user_{uuid4().hex[:8]}"
    assert (await db.set_username(alice, f"  {name}  ")).username == name
    await db.ensure_profile(bob, "bob@example.com")
    with pytest.raises(UsernameTaken):
        await db.set_username(bob, name)
