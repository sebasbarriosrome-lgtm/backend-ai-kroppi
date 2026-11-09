create or replace function public.confirm_wompi_payment(
  p_reference text,
  p_transaction_id text,
  p_amount_in_cents bigint,
  p_currency text,
  p_status text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_payment record;
  v_plan_type text;
  v_premium_until timestamptz;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  if coalesce(auth.role(), '') <> 'service_role' then
    raise exception 'forbidden' using errcode = '42501';
  end if;

  if nullif(p_reference, '') is null
     or nullif(p_transaction_id, '') is null
     or p_amount_in_cents is null
     or nullif(p_currency, '') is null
     or p_status is null
     or p_status not in ('pending', 'approved', 'declined', 'voided', 'error') then
    return pg_catalog.jsonb_build_object('result', 'invalid');
  end if;

  select p.id, p.user_id, p.provider, p.amount_in_cents, p.currency,
         p.status, p.provider_transaction_id, p.paid_at
    into v_payment
    from public.payments as p
   where p.reference = p_reference
   for update;

  if not found then
    return pg_catalog.jsonb_build_object('result', 'not_found');
  end if;

  if v_payment.provider is distinct from 'wompi'
     or v_payment.amount_in_cents is distinct from p_amount_in_cents
     or v_payment.currency is distinct from p_currency
     or v_payment.user_id is null then
    return pg_catalog.jsonb_build_object('result', 'mismatch');
  end if;

  if v_payment.provider_transaction_id is not null
     and v_payment.provider_transaction_id is distinct from p_transaction_id then
    return pg_catalog.jsonb_build_object('result', 'transaction_conflict');
  end if;

  if exists (
    select 1
      from public.payments as other_payment
     where other_payment.provider_transaction_id = p_transaction_id
       and other_payment.id <> v_payment.id
  ) then
    return pg_catalog.jsonb_build_object('result', 'transaction_conflict');
  end if;

  select profile.plan_type, profile.premium_until
    into v_plan_type, v_premium_until
    from public.profiles as profile
   where profile.id = v_payment.user_id
   for update;

  if not found then
    return pg_catalog.jsonb_build_object('result', 'invalid_user');
  end if;

  if v_payment.status = 'approved' then
    return pg_catalog.jsonb_build_object('result', 'already_processed');
  end if;

  update public.payments
     set provider_transaction_id = p_transaction_id,
         status = p_status,
         paid_at = case
           when p_status = 'approved' then coalesce(v_payment.paid_at, v_now)
           else v_payment.paid_at
         end,
         updated_at = v_now
   where id = v_payment.id;

  if p_status = 'approved' then
    update public.profiles
       set plan_type = 'premium',
           premium_until =
         case
           when v_plan_type = 'premium' and v_premium_until > v_now
             then v_premium_until
           else v_now
         end + interval '30 days'
     where id = v_payment.user_id;
  end if;

  return pg_catalog.jsonb_build_object('result', 'processed');
exception
  when unique_violation then
    return pg_catalog.jsonb_build_object('result', 'transaction_conflict');
end;
$$;

revoke all on function public.confirm_wompi_payment(text, text, bigint, text, text)
  from public, anon, authenticated;
grant execute on function public.confirm_wompi_payment(text, text, bigint, text, text)
  to service_role;
