-- Run in the Supabase SQL editor. Also create a PRIVATE storage bucket named "documents".

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text unique,
  updated_at timestamptz default now()
);

create table if not exists public.documents (
  id uuid primary key,
  owner_id uuid references auth.users(id) on delete cascade,  -- null for global corpus
  is_global boolean not null default false,
  name text not null,
  sha256 text not null,
  storage_path text not null,
  status text not null default 'processing' check (status in ('processing','ready','failed')),
  stage text,
  error text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index if not exists documents_owner_idx on public.documents(owner_id);
create index if not exists documents_hash_idx on public.documents(owner_id, sha256);

alter table public.profiles enable row level security;
alter table public.documents enable row level security;

create policy "own profile" on public.profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

create policy "read own or global documents" on public.documents
  for select using (auth.uid() = owner_id or is_global);
-- All writes to documents go through the backend using the service role key.
