begin;

-- An explicit plan change and any quota-consuming write for the same
-- account commit in a single order. The transition only changes the profile.
create function public.serialize_subscription_change()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
begin
  perform public.lock_subscription_writes(new.id);
  return new;
end;
$$;

revoke all on function public.serialize_subscription_change() from public, anon, authenticated;

create trigger serialize_subscription_change
after update on public.profiles
for each row when (
  old.plan_type is distinct from new.plan_type
  or old.premium_until is distinct from new.premium_until
)
execute function public.serialize_subscription_change();

commit;
