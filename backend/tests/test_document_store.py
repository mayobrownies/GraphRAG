import os
from uuid import uuid4

import pytest
from supabase import acreate_client

from app.repositories.document_store import DocumentStore

# There is no in-memory Supabase, so the bucket tests need a dev project and bucket
SUPABASE_TEST_URL = os.getenv("SUPABASE_TEST_URL")
SUPABASE_TEST_KEY = os.getenv("SUPABASE_TEST_KEY")
SUPABASE_TEST_BUCKET = os.getenv("SUPABASE_TEST_BUCKET")
needs_supabase = pytest.mark.skipif(
    not (SUPABASE_TEST_URL and SUPABASE_TEST_KEY and SUPABASE_TEST_BUCKET),
    reason="set SUPABASE_TEST_URL, SUPABASE_TEST_KEY and SUPABASE_TEST_BUCKET to run",
)


def test_path_for_own_document():
    assert DocumentStore.path_for("doc-1", "user-1") == "user-1/doc-1.pdf"


def test_path_for_global_document():
    assert DocumentStore.path_for("doc-1", None) == "global/doc-1.pdf"


@pytest.fixture
async def store():
    client = await acreate_client(SUPABASE_TEST_URL, SUPABASE_TEST_KEY)
    yield DocumentStore(client=client, bucket=SUPABASE_TEST_BUCKET)


@pytest.fixture
def path():
    return DocumentStore.path_for(str(uuid4()), "test-user")


@needs_supabase
async def test_upload_then_download(store, path):
    assert await store.upload(path, b"%PDF-1 first") == path
    assert await store.download(path) == b"%PDF-1 first"
    await store.delete(path)


@needs_supabase
async def test_upload_to_existing_path_fails(store, path):
    await store.upload(path, b"%PDF-1 first")
    with pytest.raises(Exception):
        await store.upload(path, b"%PDF-1 second")
    await store.delete(path)


@needs_supabase
async def test_replace_overwrites(store, path):
    await store.upload(path, b"%PDF-1 first")
    assert await store.replace(path, b"%PDF-1 second") == path
    assert await store.download(path) == b"%PDF-1 second"
    await store.delete(path)


@needs_supabase
async def test_signed_url(store, path):
    await store.upload(path, b"%PDF-1 first")
    url = await store.signed_url(path, expires_in=60)
    assert url.startswith("http") and "token=" in url
    await store.delete(path)


@needs_supabase
async def test_delete(store, path):
    await store.upload(path, b"%PDF-1 first")
    assert await store.delete(path) is True
    assert await store.delete(path) is False
    with pytest.raises(Exception):
        await store.download(path)
