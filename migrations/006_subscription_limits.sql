begin;

create table public.diagnosis_quota_usage (
  diagnosis_id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  period_start date not null
);
create index diagnosis_quota_usage_owner_period
  on public.diagnosis_quota_usage (user_id, period_start);
alter table public.diagnosis_quota_usage enable row level security;
revoke all on public.diagnosis_quota_usage from public, anon, authenticated, service_role;

create table public.subscription_write_locks (
  user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.subscription_write_locks enable row level security;
revoke all on public.subscription_write_locks from public, anon, authenticated, service_role;

create function public.lock_subscription_writes(p_user_id uuid)
returns void
language sql
set search_path = ''
as $$
  -- Update the row so higher isolation levels abort on stale snapshots.
  insert into public.subscription_write_locks (user_id) values (p_user_id)
  on conflict (user_id) do update set user_id = excluded.user_id;
$$;

create function public.subscription_access(p_user_id uuid)
returns jsonb
language sql stable security definer
set search_path = ''
as $$
  with active as (
    select premium_until
    from public.profiles
    where id = p_user_id and plan_type = 'premium' and premium_until > statement_timestamp()
  ), plan as (
    select (select premium_until from active) as expires_at,
           date_trunc('month', statement_timestamp() at time zone 'America/Bogota') as month_start
  )
  select jsonb_build_object(
    'plan_type', case when expires_at is null then 'free' else 'premium' end,
    'premium_until', expires_at,
    'limits', jsonb_build_object(
      'farms', case when expires_at is null then 1 end,
      'crops', case when expires_at is null then 2 end,
      'plots', case when expires_at is null then 5 end,
      'diagnoses', case when expires_at is null then 3 else 30 end
    ),
    'diagnosis_period', jsonb_build_object(
      'timezone', 'America/Bogota',
      'starts_at', month_start at time zone 'America/Bogota',
      'renews_at', (month_start + interval '1 month') at time zone 'America/Bogota'
    )
  ) from plan;
$$;

create function public.subscription_resource_usage(p_user_id uuid, p_resource text)
returns bigint
language plpgsql stable
set search_path = ''
as $$
begin
  case p_resource
    when 'farms' then return (select count(*) from public.farms where owner_id = p_user_id);
    when 'crops' then return (
      select count(*) from public.crops c join public.farms f on f.id = c.farm_id
      where f.owner_id = p_user_id
    );
    when 'plots' then return (
      select count(*) from public.plots p
      join public.crops c on c.id = p.crop_id join public.farms f on f.id = c.farm_id
      where f.owner_id = p_user_id
    );
    else raise exception 'Unknown subscription resource';
  end case;
end;
$$;

create function public.subscription_status(p_user_id uuid)
returns jsonb
language sql stable security definer
set search_path = ''
as $$
  with access as (select public.subscription_access(p_user_id) as data)
  select data || jsonb_build_object('usage', jsonb_build_object(
    'farms', public.subscription_resource_usage(p_user_id, 'farms'),
    'crops', public.subscription_resource_usage(p_user_id, 'crops'),
    'plots', public.subscription_resource_usage(p_user_id, 'plots'),
    'diagnoses', (
      select count(*) from public.diagnosis_quota_usage
      where user_id = p_user_id
        and period_start = ((data#>>'{diagnosis_period,starts_at}')::timestamptz
                            at time zone 'America/Bogota')::date
    )
  )) from access;
$$;

create function public.enforce_subscription_resource_limit()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
declare
  owner uuid;
  resource_limit integer;
begin
  if tg_op = 'UPDATE' then
    -- Parent links are immutable in the API and through direct writes.
    if (to_jsonb(new) -> tg_argv[0]) is distinct from (to_jsonb(old) -> tg_argv[0]) then
      raise exception 'No se puede cambiar el propietario o recurso padre.' using errcode = '23514';
    end if;
    return new;
  end if;
  case tg_table_name
    when 'farms' then owner := new.owner_id;
    when 'crops' then select f.owner_id into owner from public.farms f where f.id = new.farm_id;
    when 'plots' then
      select f.owner_id into owner from public.crops c
      join public.farms f on f.id = c.farm_id where c.id = new.crop_id;
  end case;
  if auth.role() in ('anon', 'authenticated')
     and (auth.uid() is null or owner is distinct from auth.uid()) then
    raise insufficient_privilege using message = 'El recurso debe pertenecer a tu cuenta.';
  end if;
  if owner is null then
    return new; -- Normal foreign-key and null constraints handle invalid parents.
  end if;
  perform public.lock_subscription_writes(owner);
  resource_limit := (public.subscription_access(owner) -> 'limits' ->> tg_table_name)::integer;
  if resource_limit is not null
     and public.subscription_resource_usage(owner, tg_table_name) >= resource_limit then
    raise sqlstate 'PT409' using message = case tg_table_name
      when 'farms' then 'Alcanzaste el límite de fincas de tu plan.'
      when 'crops' then 'Alcanzaste el límite de cultivos de tu plan.'
      else 'Alcanzaste el límite de lotes de tu plan.'
    end;
  end if;
  return new;
end;
$$;

create trigger enforce_subscription_limit before insert or update of owner_id on public.farms
  for each row execute function public.enforce_subscription_resource_limit('owner_id');
create trigger enforce_subscription_limit before insert or update of farm_id on public.crops
  for each row execute function public.enforce_subscription_resource_limit('farm_id');
create trigger enforce_subscription_limit before insert or update of crop_id on public.plots
  for each row execute function public.enforce_subscription_resource_limit('crop_id');

create function public.consume_diagnosis_quota(p_user_id uuid, p_diagnosis_id uuid)
returns boolean
language plpgsql security definer
set search_path = ''
as $$
declare
  access jsonb;
  month_start date;
  existing_owner uuid;
begin
  perform public.lock_subscription_writes(p_user_id);
  select user_id into existing_owner from public.diagnosis_quota_usage
  where diagnosis_id = p_diagnosis_id;
  if found then
    if existing_owner <> p_user_id then
      raise sqlstate 'PT409' using message = 'Identificador de diagnóstico en uso.';
    end if;
    return false;
  end if;
  access := public.subscription_access(p_user_id);
  month_start := ((access#>>'{diagnosis_period,starts_at}')::timestamptz at time zone 'America/Bogota')::date;
  if (select count(*) from public.diagnosis_quota_usage
      where user_id = p_user_id and period_start = month_start) >= (access#>>'{limits,diagnoses}')::integer then
    raise sqlstate 'PT429' using message = 'Agotaste la cuota mensual de diagnósticos de tu plan.';
  end if;
  insert into public.diagnosis_quota_usage values (p_diagnosis_id, p_user_id, month_start);
  return true;
end;
$$;

create function public.enforce_diagnosis_quota()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
begin
  perform public.consume_diagnosis_quota(new.user_id, new.id);
  return new;
end;
$$;

-- Serialize backfill against writes and retain usage if a diagnosis is later deleted.
lock table public.diagnostics in share row exclusive mode;
insert into public.diagnosis_quota_usage (diagnosis_id, user_id, period_start)
select d.id, d.user_id, date_trunc('month', d.created_at at time zone 'America/Bogota')::date
from public.diagnostics d join auth.users u on u.id = d.user_id
where d.created_at >= (date_trunc('month', statement_timestamp() at time zone 'America/Bogota')
                       at time zone 'America/Bogota');
create trigger enforce_diagnosis_quota before insert on public.diagnostics
  for each row execute function public.enforce_diagnosis_quota();

create function public.protect_subscription_profile()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if current_user in ('anon', 'authenticated') or auth.role() in ('anon', 'authenticated') then
    if tg_op = 'INSERT' then
      if lower(coalesce(new.plan_type::text, 'free')) <> 'free' or new.premium_until is not null then
        raise insufficient_privilege using message = 'El plan se administra desde el servidor.';
      end if;
    elsif new.plan_type is distinct from old.plan_type
       or new.premium_until is distinct from old.premium_until
       or new.id is distinct from old.id then
      raise insufficient_privilege using message = 'El plan se administra desde el servidor.';
    end if;
  end if;
  return new;
end;
$$;

create trigger protect_subscription_profile before insert or update on public.profiles
  for each row execute function public.protect_subscription_profile();

revoke all on function public.subscription_access(uuid), public.subscription_status(uuid),
  public.subscription_resource_usage(uuid, text), public.consume_diagnosis_quota(uuid, uuid),
  public.lock_subscription_writes(uuid),
  public.enforce_subscription_resource_limit(), public.enforce_diagnosis_quota(),
  public.protect_subscription_profile() from public, anon, authenticated;
grant execute on function public.subscription_access(uuid), public.subscription_status(uuid),
  public.consume_diagnosis_quota(uuid, uuid) to service_role;

create function public.my_subscription_is_premium()
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select public.subscription_access(auth.uid())->>'plan_type' = 'premium';
$$;
revoke all on function public.my_subscription_is_premium() from public, anon;
grant execute on function public.my_subscription_is_premium() to authenticated;

revoke insert, update, truncate on public.diagnostics from public, anon, authenticated;
revoke insert, update, delete, truncate on public.payments from public, anon, authenticated;
revoke delete, truncate on public.profiles from public, anon, authenticated;

alter table public.diagnostics enable row level security;
alter table public.plot_reports enable row level security;
alter table public.loss_estimations enable row level security;
alter table public.harvests enable row level security;
alter table public.care_activities enable row level security;

create policy subscription_diagnosis_history on public.diagnostics
  as restrictive for select to authenticated using (
    (select public.my_subscription_is_premium()) or
    created_at >= (date_trunc('month', statement_timestamp() at time zone 'America/Bogota')
                   at time zone 'America/Bogota')
  );
create policy subscription_diagnosis_insert on public.diagnostics
  as restrictive for insert to anon, authenticated with check (false);
create policy subscription_diagnosis_update on public.diagnostics
  as restrictive for update to anon, authenticated using (false) with check (false);
create policy subscription_report_access on public.plot_reports
  as restrictive for all to authenticated using ((select public.my_subscription_is_premium()));
create policy subscription_loss_access on public.loss_estimations
  as restrictive for all to authenticated using ((select public.my_subscription_is_premium()));
create policy subscription_harvest_history on public.harvests
  as restrictive for select to authenticated using ((select public.my_subscription_is_premium()));
create policy subscription_care_history on public.care_activities
  as restrictive for select to authenticated using ((select public.my_subscription_is_premium()));
create policy subscription_report_storage on storage.objects
  as restrictive for all to authenticated using (
    bucket_id <> 'reports' or (select public.my_subscription_is_premium())
  );
create policy subscription_diagnosis_storage on storage.objects
  as restrictive for select to authenticated using (
    bucket_id <> 'diagnosticos' or (select public.my_subscription_is_premium()) or exists (
      select 1 from public.diagnostics d
      where d.user_id = (select auth.uid()) and d.image_url = objects.name
    )
  );

commit;
