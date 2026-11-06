create or replace function public.validate_plot_area_within_farm()
returns trigger
language plpgsql
as $$
declare
  target_farm_id uuid;
  farm_area numeric;
  used_area numeric;
begin
  select c.farm_id, f.area_ha
    into target_farm_id, farm_area
    from public.crops c
    join public.farms f on f.id = c.farm_id
   where c.id = new.crop_id;

  if target_farm_id is null or farm_area is null then
    return new;
  end if;

  perform 1 from public.farms where id = target_farm_id for update;
  select area_ha into farm_area from public.farms where id = target_farm_id;

  select coalesce(sum(p.area_ha), 0)
    into used_area
    from public.plots p
    join public.crops c on c.id = p.crop_id
   where c.farm_id = target_farm_id
     and p.id is distinct from new.id;

  if used_area + new.area_ha > farm_area then
    raise exception 'El área total de los lotes (%) supera el área de la finca (%) hectáreas.',
      used_area + new.area_ha, farm_area
      using errcode = '23514';
  end if;

  return new;
end;
$$;

drop trigger if exists plots_farm_area_limit on public.plots;
create trigger plots_farm_area_limit
before insert or update of crop_id, area_ha on public.plots
for each row execute function public.validate_plot_area_within_farm();

create or replace function public.validate_farm_area_with_existing_plots()
returns trigger
language plpgsql
as $$
declare
  used_area numeric;
begin
  if new.area_ha is null then
    return new;
  end if;

  perform 1 from public.farms where id = new.id for update;

  select coalesce(sum(p.area_ha), 0)
    into used_area
    from public.plots p
    join public.crops c on c.id = p.crop_id
   where c.farm_id = new.id;

  if used_area > new.area_ha then
    raise exception 'El área de la finca no puede ser menor que el área ocupada por sus lotes (% hectáreas).',
      used_area
      using errcode = '23514';
  end if;

  return new;
end;
$$;

drop trigger if exists farms_area_limit on public.farms;
create trigger farms_area_limit
before update of area_ha on public.farms
for each row execute function public.validate_farm_area_with_existing_plots();
