-- Supabase Postgres schema. Run in the Supabase SQL editor; the script must be safe to run more than once
-- (create ... if not exists for tables and indexes, drop policy if exists before each create policy)
-- Also create a PRIVATE storage bucket; its name must match SUPABASE_STORAGE_BUCKET in .env and render.yaml
-- profiles: one row per account (id = auth.users id), custom username unique and 3-30 characters
--   Created on first sign-in, either by a trigger on auth.users or by GET /api/me upserting it
-- documents: metadata and processing state for every PDF
--   id, owner_id (null for the global corpus), is_global, name, sha256, storage_path
--   status in ('processing', 'ready', 'failed'), stage (progress message), error (short message for the user)
--   created_at, updated_at (set on every status change)
--   is_global must be true exactly when owner_id is null
--   unique nulls not distinct (owner_id, sha256) so the database also blocks duplicate uploads
-- hidden_documents: (user_id, document_id) for global corpus documents a user removed from their workspace
--   Removing a global document only affects that account (SDD 2.2, 4.3)
-- Row level security on every table
--   profiles: a user can read and update only their own row
--   documents: a user can read their own documents, plus global ones they haven't hidden
--   All writes go through the backend with the secret key
-- The secret key bypasses RLS, so document_db.py must still filter by owner and hidden_documents
-- Chunks, embeddings, and graph data are not stored here. They live in Qdrant and Neo4j, linked by document id

create table if not exists public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    email text,
    -- null until the user picks one
    username text unique check (char_length(username) between 3 and 30),
    created_at timestamptz not null default now()
);

create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid references auth.users (id) on delete cascade,
    is_global boolean not null,
    name text not null,
    sha256 text not null,
    storage_path text not null,
    status text not null default 'processing' check (status in ('processing', 'ready', 'failed')),
    stage text,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (is_global = (owner_id is null)),
    unique nulls not distinct (owner_id, sha256)
);

create index if not exists documents_owner_id_idx on public.documents (owner_id);

create table if not exists public.hidden_documents (
    user_id uuid not null references auth.users (id) on delete cascade,
    document_id uuid not null references public.documents (id) on delete cascade,
    primary key (user_id, document_id)
);

create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists documents_set_updated_at on public.documents;
create trigger documents_set_updated_at
    before update on public.documents
    for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.documents enable row level security;
alter table public.hidden_documents enable row level security;

drop policy if exists "profiles: read own" on public.profiles;
create policy "profiles: read own" on public.profiles
    for select to authenticated using (id = auth.uid());

drop policy if exists "profiles: update own" on public.profiles;
create policy "profiles: update own" on public.profiles
    for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists "documents: read own and visible global" on public.documents;
create policy "documents: read own and visible global" on public.documents
    for select to authenticated using (
        owner_id = auth.uid()
        or (
            is_global
            and not exists (
                select 1 from public.hidden_documents h
                where h.document_id = documents.id and h.user_id = auth.uid()
            )
        )
    );

drop policy if exists "hidden_documents: read own" on public.hidden_documents;
create policy "hidden_documents: read own" on public.hidden_documents
    for select to authenticated using (user_id = auth.uid());
