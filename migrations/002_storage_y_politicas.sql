-- Kroppi: bucket privado de fotos + políticas de lectura (RLS).
-- Seguro de ejecutar más de una vez. No modifica tablas ni columnas.
-- El backend escribe con rol de servidor (se salta RLS); estas políticas
-- son para lo que la app lea directamente desde Supabase.

alter table public.crops       enable row level security;
alter table public.diseases    enable row level security;
alter table public.diagnostics enable row level security;

-- Catálogo: lectura para usuarios con sesión.
drop policy if exists "crops_leer_autenticados" on public.crops;
create policy "crops_leer_autenticados" on public.crops
  for select to authenticated using (true);

drop policy if exists "diseases_leer_autenticados" on public.diseases;
create policy "diseases_leer_autenticados" on public.diseases
  for select to authenticated using (true);

-- Diagnósticos: cada usuario ve y borra SOLO los suyos.
drop policy if exists "diagnostics_leer_propios" on public.diagnostics;
create policy "diagnostics_leer_propios" on public.diagnostics
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists "diagnostics_borrar_propios" on public.diagnostics;
create policy "diagnostics_borrar_propios" on public.diagnostics
  for delete to authenticated using (user_id = (select auth.uid()));

-- Bucket PRIVADO. Fotos como {user_id}/{diagnostico_id}.jpg
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('diagnosticos', 'diagnosticos', false, 10485760, array['image/jpeg'])
on conflict (id) do nothing;

drop policy if exists "diagnosticos_leer_propias" on storage.objects;
create policy "diagnosticos_leer_propias" on storage.objects
  for select to authenticated
  using (
    bucket_id = 'diagnosticos'
    and (storage.foldername(name))[1] = (select auth.uid())::text
  );
