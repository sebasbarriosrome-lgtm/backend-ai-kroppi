-- Minimal schema for testing the production migrations in a disposable PostgreSQL database.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role bypassrls;
  end if;
end $$;

create schema auth;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;
create function auth.role() returns text language sql stable as $$
  select current_setting('request.jwt.claim.role', true);
$$;
grant usage on schema auth to anon, authenticated, service_role;

create schema storage;
create table storage.buckets (
  id text primary key, name text, public boolean, file_size_limit bigint, allowed_mime_types text[]
);
create table storage.objects (id uuid primary key, bucket_id text, name text);
alter table storage.objects enable row level security;
create function storage.foldername(name text) returns text[] language sql immutable as $$
  select (string_to_array(name, '/'))[:cardinality(string_to_array(name, '/'))-1];
$$;

create table public.profiles (
  id uuid primary key references auth.users,
  plan_type text default 'free', premium_until timestamptz, full_name text
);
create table public.farms (
  id uuid primary key default gen_random_uuid(), owner_id uuid not null references auth.users,
  name text, area_ha numeric
);
create table public.crops (
  id uuid primary key default gen_random_uuid(), farm_id uuid not null references public.farms,
  name text, is_active boolean default true
);
create table public.plots (
  id uuid primary key default gen_random_uuid(), crop_id uuid not null references public.crops,
  name text, area_ha numeric not null default 1
);
create table public.plot_samples (
  id uuid primary key default gen_random_uuid(), plot_id uuid not null references public.plots
);
create table public.diagnostics (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users,
  created_at timestamptz not null default now(), image_url text,
  plot_samples_id uuid references public.plot_samples
);
create table public.harvests (
  id uuid primary key default gen_random_uuid(), plot_id uuid references public.plots
);
create table public.loss_estimations (id uuid primary key default gen_random_uuid());
create table public.payments (
  id uuid primary key default gen_random_uuid(), user_id uuid references auth.users,
  reference text unique, provider text, amount_in_cents bigint, currency text, status text,
  provider_transaction_id text unique, paid_at timestamptz, updated_at timestamptz
);

grant usage on schema storage to authenticated, service_role;
grant select, insert, update, delete on all tables in schema public to authenticated, service_role;
grant select, insert, update, delete on storage.objects to authenticated, service_role;
-- Owner policies emulate the authenticated farm-management paths.
alter table public.farms enable row level security;
alter table public.crops enable row level security;
alter table public.plots enable row level security;
create policy test_farms_owner on public.farms for all to authenticated
  using (owner_id = auth.uid());
create policy test_crops_owner on public.crops for all to authenticated
  using (exists (select 1 from public.farms f where f.id = farm_id));
create policy test_plots_owner on public.plots for all to authenticated
  using (exists (select 1 from public.crops c where c.id = crop_id));
-- Permissive policies ensure the tests exercise the new restrictive policies.
create policy test_diagnostics_owner on public.diagnostics for all to authenticated
  using (user_id = auth.uid());
create policy test_harvests on public.harvests for all to authenticated using (true);
create policy test_losses on public.loss_estimations for all to authenticated using (true);
create policy test_storage on storage.objects for all to authenticated using (true);
