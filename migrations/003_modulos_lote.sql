-- Tablas de cuidados e informes, controladas por propietario y buckets privados.
create table if not exists public.care_activities (
  id uuid primary key default gen_random_uuid(),
  plot_id uuid not null references public.plots(id) on delete cascade,
  created_by uuid not null default auth.uid() references public.profiles(id),
  applied_at date not null,
  activity_type text not null check (activity_type in (
    'FERTILIZATION','FUNGICIDE','INSECTICIDE','HERBICIDE','PRUNING',
    'WEEDING','IRRIGATION','CULTURAL_CONTROL','OTHER')),
  product_name text,
  active_ingredient text,
  quantity numeric check (quantity is null or quantity > 0),
  quantity_unit text check (quantity_unit is null or quantity_unit in ('kg','g','L','mL','unit')),
  application_method text check (application_method is null or application_method in (
    'SPRAYING','DRENCH','BROADCAST','MANUAL','DRIP','OTHER')),
  target_disease_code text,
  cost numeric check (cost is null or cost >= 0),
  currency char(3) not null default 'COP',
  evidence_path text,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.plot_reports (
  id uuid primary key default gen_random_uuid(),
  plot_id uuid not null references public.plots(id) on delete cascade,
  created_by uuid not null default auth.uid() references public.profiles(id),
  period_from date not null,
  period_to date not null,
  file_path text,
  file_size_bytes integer check (file_size_bytes is null or file_size_bytes >= 0),
  summary jsonb,
  created_at timestamptz not null default now(),
  check (period_to >= period_from)
);

create index if not exists care_activities_plot_date_idx
  on public.care_activities (plot_id, applied_at desc);
create index if not exists plot_reports_plot_idx
  on public.plot_reports (plot_id, created_at desc);

create or replace function public.update_care_activities_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists care_activities_updated_at on public.care_activities;
create trigger care_activities_updated_at
before update on public.care_activities
for each row execute function public.update_care_activities_updated_at();

alter table public.care_activities enable row level security;
alter table public.plot_reports enable row level security;

drop policy if exists care_activities_owner on public.care_activities;
create policy care_activities_owner on public.care_activities
for all to authenticated
using (exists (
  select 1 from public.plots p
  join public.crops c on c.id = p.crop_id
  join public.farms f on f.id = c.farm_id
  where p.id = care_activities.plot_id and f.owner_id = (select auth.uid())
))
with check (exists (
  select 1 from public.plots p
  join public.crops c on c.id = p.crop_id
  join public.farms f on f.id = c.farm_id
  where p.id = care_activities.plot_id and f.owner_id = (select auth.uid())
));

drop policy if exists plot_reports_owner on public.plot_reports;
create policy plot_reports_owner on public.plot_reports
for all to authenticated
using (exists (
  select 1 from public.plots p
  join public.crops c on c.id = p.crop_id
  join public.farms f on f.id = c.farm_id
  where p.id = plot_reports.plot_id and f.owner_id = (select auth.uid())
))
with check (exists (
  select 1 from public.plots p
  join public.crops c on c.id = p.crop_id
  join public.farms f on f.id = c.farm_id
  where p.id = plot_reports.plot_id and f.owner_id = (select auth.uid())
));

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('care-evidence', 'care-evidence', false, 10485760, array['image/jpeg','image/png','image/webp']),
  ('reports', 'reports', false, 15728640, array['application/pdf'])
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists care_evidence_owner on storage.objects;
create policy care_evidence_owner on storage.objects
for all to authenticated
using (
  bucket_id = 'care-evidence'
  and (storage.foldername(name))[1] = (select auth.uid())::text
)
with check (
  bucket_id = 'care-evidence'
  and (storage.foldername(name))[1] = (select auth.uid())::text
);

drop policy if exists reports_owner on storage.objects;
create policy reports_owner on storage.objects
for all to authenticated
using (
  bucket_id = 'reports'
  and (storage.foldername(name))[1] = (select auth.uid())::text
)
with check (
  bucket_id = 'reports'
  and (storage.foldername(name))[1] = (select auth.uid())::text
);
