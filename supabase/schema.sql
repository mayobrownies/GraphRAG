-- Supabase Postgres schema. Run in the Supabase SQL editor; the script must be safe to run more than once
-- (create ... if not exists for tables and indexes, drop policy if exists before each create policy)
-- Also create a PRIVATE storage bucket; its name must match SUPABASE_STORAGE_BUCKET in .env and render.yaml
-- profiles: one row per account (id = auth.users id), custom username unique and 3-30 characters
--   Created on first sign-in, either by a trigger on auth.users or by GET /api/me upserting it
-- documents: the user's library, metadata and processing state for every PDF they uploaded
--   id, owner_id, name, sha256, storage_path
--   status in ('processing', 'ready', 'failed'), stage (progress message), error (short message for the user)
--   created_at, updated_at (set on every status change)
--   unique (owner_id, sha256) so the database also blocks duplicate uploads
-- groups: named sets of library papers (e.g. "Medical research"), unique name per owner
--   Every user has at least one; GET /api/groups creates "Group 1" when they have none
-- group_documents: which library papers are in which group; a paper can be in several groups
--   Removing a paper from a group keeps it in the library; deleting the paper or the group cascades here
--   Composite foreign keys on (id, owner_id) make a group and its papers always belong to the same user
-- Row level security on every table
--   profiles: a user can read and update only their own row
--   documents, groups, group_documents: a user can read only their own rows
--   All writes go through the backend with the secret key
-- The secret key bypasses RLS, so document_db.py must still filter every query by owner
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
    owner_id uuid not null references auth.users (id) on delete cascade,
    name text not null,
    sha256 text not null,
    storage_path text not null,
    status text not null default 'processing' check (status in ('processing', 'ready', 'failed')),
    stage text,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, sha256)
);

-- Migration from the global corpus for databases created by an older version of this script; no-ops otherwise
-- Global PDFs under global/ in the storage bucket must be deleted from the Supabase dashboard
drop policy if exists "documents: read own and visible global" on public.documents;
drop table if exists public.hidden_documents;
delete from public.documents where owner_id is null;
alter table public.documents drop column if exists is_global;
alter table public.documents alter column owner_id set not null;

create index if not exists documents_owner_id_idx on public.documents (owner_id);
-- Target of the composite foreign key from group_documents
create unique index if not exists documents_id_owner_id_idx on public.documents (id, owner_id);

create table if not exists public.groups (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users (id) on delete cascade,
    name text not null check (name = btrim(name) and char_length(name) between 1 and 100),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, name),
    unique (id, owner_id)
);

create table if not exists public.group_documents (
    group_id uuid not null,
    document_id uuid not null,
    owner_id uuid not null,
    added_at timestamptz not null default now(),
    primary key (group_id, document_id),
    foreign key (group_id, owner_id) references public.groups (id, owner_id) on delete cascade,
    foreign key (document_id, owner_id) references public.documents (id, owner_id) on delete cascade
);

create index if not exists group_documents_document_id_idx on public.group_documents (document_id);
create index if not exists group_documents_owner_id_idx on public.group_documents (owner_id);

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

drop trigger if exists groups_set_updated_at on public.groups;
create trigger groups_set_updated_at
    before update on public.groups
    for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.documents enable row level security;
alter table public.groups enable row level security;
alter table public.group_documents enable row level security;

drop policy if exists "profiles: read own" on public.profiles;
create policy "profiles: read own" on public.profiles
    for select to authenticated using (id = auth.uid());

drop policy if exists "profiles: update own" on public.profiles;
create policy "profiles: update own" on public.profiles
    for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists "documents: read own" on public.documents;
create policy "documents: read own" on public.documents
    for select to authenticated using (owner_id = auth.uid());

drop policy if exists "groups: read own" on public.groups;
create policy "groups: read own" on public.groups
    for select to authenticated using (owner_id = auth.uid());

drop policy if exists "group_documents: read own" on public.group_documents;
create policy "group_documents: read own" on public.group_documents
    for select to authenticated using (owner_id = auth.uid());
