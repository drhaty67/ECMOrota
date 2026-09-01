-- Apply after flexible_fallback_v4.sql.
-- Replaces the inherited destructive save function. Configuration changes must
-- never delete solver_runs, rota_drafts or assignments because those tables are
-- the immutable audit history.

create or replace function public.save_rota_configuration(p_workspace_id text, p_state jsonb)
returns void
language plpgsql
security invoker
set search_path = public
as $$
declare
  item jsonb;
  consultant_key text;
  special_value jsonb;
  partner_value text;
begin
  insert into rota_workspaces(id)
  values (p_workspace_id)
  on conflict (id) do update set updated_at = now();

  insert into rota_periods(workspace_id, name, start_date, end_date, status)
  values (
    p_workspace_id,
    p_state#>>'{period,name}',
    (p_state#>>'{period,start}')::date,
    (p_state#>>'{period,end}')::date,
    coalesce(p_state#>>'{period,status}', 'Draft')
  )
  on conflict (workspace_id) do update set
    name = excluded.name,
    start_date = excluded.start_date,
    end_date = excluded.end_date,
    status = excluded.status,
    updated_at = now();

  -- Preserve consultant rows referenced by historical assignments. Consultants
  -- absent from the current payload are deactivated rather than deleted.
  update consultants set active = false, updated_at = now()
  where workspace_id = p_workspace_id;

  for item in
    select * from jsonb_array_elements(coalesce(p_state->'consultants', '[]'::jsonb))
  loop
    insert into consultants(id, workspace_id, name, email, active)
    values (
      item->>'id', p_workspace_id, item->>'name',
      coalesce(item->>'email', ''), coalesce((item->>'active')::boolean, true)
    )
    on conflict (id) do update set
      name = excluded.name,
      email = excluded.email,
      active = excluded.active,
      updated_at = now();
  end loop;

  -- These are current configuration tables, not audit-history tables, so they
  -- may be replaced transactionally from the application state.
  delete from split_partner_preferences where workspace_id = p_workspace_id;
  delete from consultant_period_settings where workspace_id = p_workspace_id;
  delete from week_preferences where workspace_id = p_workspace_id;
  delete from absences where workspace_id = p_workspace_id;
  delete from workload_targets where workspace_id = p_workspace_id;

  for consultant_key, item in
    select * from jsonb_each(coalesce(p_state->'targets', '{}'::jsonb))
  loop
    insert into workload_targets(workspace_id, consultant_id, t_blocks, weekend_credits, c_blocks)
    values (
      p_workspace_id, consultant_key,
      coalesce((item->>'t')::int, 0),
      coalesce((item->>'weekend')::int, 0),
      coalesce((item->>'c')::int, 0)
    );
  end loop;

  for item in
    select * from jsonb_array_elements(coalesce(p_state->'absences', '[]'::jsonb))
  loop
    insert into absences(id, workspace_id, consultant_id, absence_type, start_date, end_date, notes)
    values (
      item->>'id', p_workspace_id, item->>'consultant_id', item->>'type',
      (item->>'start')::date, (item->>'end')::date, coalesce(item->>'notes', '')
    );
  end loop;

  for item in
    select * from jsonb_array_elements(coalesce(p_state->'preferences', '[]'::jsonb))
  loop
    insert into week_preferences(id, workspace_id, consultant_id, week_commencing, direction, duty_scope, priority, notes)
    values (
      item->>'id', p_workspace_id, item->>'consultant_id',
      (item->>'week')::date, item->>'direction', item->>'scope',
      item->>'priority', coalesce(item->>'notes', '')
    );
  end loop;

  for consultant_key, special_value in
    select * from jsonb_each(coalesce(p_state->'special', '{}'::jsonb))
  loop
    insert into consultant_period_settings(workspace_id, consultant_id, weekend_mode, notes)
    values (
      p_workspace_id, consultant_key,
      coalesce(special_value->>'weekend_mode', 'Standard'),
      coalesce(special_value->>'notes', '')
    );
    for partner_value in
      select * from jsonb_array_elements_text(coalesce(special_value->'partner_ids', '[]'::jsonb))
    loop
      insert into split_partner_preferences(workspace_id, consultant_id, partner_id)
      values (p_workspace_id, consultant_key, partner_value);
    end loop;
  end loop;

  -- Deliberately no DELETE/UPDATE/INSERT against solver_runs, rota_drafts or
  -- assignments. Historical generation records remain immutable.
end;
$$;

-- Keep older deployed application code safe immediately after this migration.
create or replace function public.save_rota_state(p_workspace_id text, p_state jsonb)
returns void
language plpgsql
security invoker
set search_path = public
as $$
begin
  perform public.save_rota_configuration(p_workspace_id, p_state);
end;
$$;

revoke all on function public.save_rota_configuration(text, jsonb) from public, anon, authenticated;
revoke all on function public.save_rota_state(text, jsonb) from public, anon, authenticated;
grant execute on function public.save_rota_configuration(text, jsonb) to service_role;
grant execute on function public.save_rota_state(text, jsonb) to service_role;
