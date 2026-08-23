-- Consultant Rota Drafting: initial Supabase schema
-- Run this entire file once in Supabase Dashboard → SQL Editor.

create table if not exists public.rota_workspaces (
  id text primary key,
  name text not null default 'Consultant Rota',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.rota_periods (
  workspace_id text primary key references public.rota_workspaces(id) on delete cascade,
  name text not null,
  start_date date not null,
  end_date date not null,
  status text not null default 'Draft',
  updated_at timestamptz not null default now(),
  constraint valid_period_dates check (end_date > start_date)
);

create table if not exists public.consultants (
  id text primary key,
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  name text not null,
  email text not null default '',
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, name)
);

create table if not exists public.workload_targets (
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  consultant_id text not null references public.consultants(id) on delete cascade,
  t_blocks integer not null default 0 check (t_blocks >= 0),
  weekend_credits integer not null default 0 check (weekend_credits >= 0),
  c_blocks integer not null default 0 check (c_blocks >= 0),
  primary key (workspace_id, consultant_id)
);

create table if not exists public.absences (
  id text primary key,
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  consultant_id text not null references public.consultants(id) on delete cascade,
  absence_type text not null check (absence_type in ('Annual leave', 'Study leave', 'NOC')),
  start_date date not null,
  end_date date not null,
  notes text not null default '',
  constraint valid_absence_dates check (end_date >= start_date)
);

create table if not exists public.week_preferences (
  id text primary key,
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  consultant_id text not null references public.consultants(id) on delete cascade,
  week_commencing date not null,
  direction text not null check (direction in ('Wants to work', 'Prefers not to work', 'Must work', 'Must not work')),
  duty_scope text not null check (duty_scope in ('Any', 'C1', 'C2', 'T', 'Weekend')),
  priority text not null check (priority in ('Low', 'Normal', 'High')),
  notes text not null default ''
);

create table if not exists public.consultant_period_settings (
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  consultant_id text not null references public.consultants(id) on delete cascade,
  weekend_mode text not null default 'Standard' check (weekend_mode in ('Standard', 'Split')),
  notes text not null default '',
  primary key (workspace_id, consultant_id)
);

create table if not exists public.split_partner_preferences (
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  consultant_id text not null references public.consultants(id) on delete cascade,
  partner_id text not null references public.consultants(id) on delete cascade,
  primary key (workspace_id, consultant_id, partner_id),
  constraint cannot_partner_self check (consultant_id <> partner_id)
);

create table if not exists public.solver_runs (
  id bigint generated always as identity primary key,
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  run_at timestamptz not null default now(),
  status text not null,
  payload jsonb not null default '{}'::jsonb
);

create table if not exists public.assignments (
  id bigint generated always as identity primary key,
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  consultant_id text not null references public.consultants(id) on delete cascade,
  week_commencing date not null,
  assignment_type text not null check (assignment_type in ('C1', 'C2', 'T', 'Weekend', 'Half A', 'Half B')),
  is_final boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists public.admin_users (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  unique (email)
);

create index if not exists consultants_workspace_idx on public.consultants(workspace_id);
create index if not exists absences_workspace_consultant_idx on public.absences(workspace_id, consultant_id);
create index if not exists preferences_workspace_consultant_idx on public.week_preferences(workspace_id, consultant_id);
create index if not exists assignments_workspace_week_idx on public.assignments(workspace_id, week_commencing);

-- The app uses a server-side service-role key. RLS is enabled and no anon/authenticated
-- policies are created, so browser clients cannot read or write these tables.
alter table public.rota_workspaces enable row level security;
alter table public.rota_periods enable row level security;
alter table public.consultants enable row level security;
alter table public.workload_targets enable row level security;
alter table public.absences enable row level security;
alter table public.week_preferences enable row level security;
alter table public.consultant_period_settings enable row level security;
alter table public.split_partner_preferences enable row level security;
alter table public.solver_runs enable row level security;
alter table public.assignments enable row level security;
alter table public.admin_users enable row level security;

-- Authenticated users can only read their own administrator record. All changes
-- to the allowlist must be made by a service role or in the Supabase SQL Editor.
drop policy if exists "Administrators can verify their own access" on public.admin_users;
create policy "Administrators can verify their own access"
on public.admin_users for select
to authenticated
using ((select auth.uid()) = user_id and active = true);

create or replace function public.load_rota_state(p_workspace_id text)
returns jsonb
language sql
security invoker
set search_path = public
as $$
  select case when w.id is null then null else jsonb_build_object(
    'period', jsonb_build_object('name', rp.name, 'start', rp.start_date, 'end', rp.end_date, 'status', rp.status),
    'consultants', coalesce((select jsonb_agg(jsonb_build_object('id', c.id, 'name', c.name, 'email', c.email, 'active', c.active) order by c.name) from consultants c where c.workspace_id = w.id), '[]'::jsonb),
    'absences', coalesce((select jsonb_agg(jsonb_build_object('id', a.id, 'consultant_id', a.consultant_id, 'type', a.absence_type, 'start', a.start_date, 'end', a.end_date, 'notes', a.notes) order by a.start_date) from absences a where a.workspace_id = w.id), '[]'::jsonb),
    'targets', coalesce((select jsonb_object_agg(t.consultant_id, jsonb_build_object('t', t.t_blocks, 'weekend', t.weekend_credits, 'c', t.c_blocks)) from workload_targets t where t.workspace_id = w.id), '{}'::jsonb),
    'preferences', coalesce((select jsonb_agg(jsonb_build_object('id', p.id, 'consultant_id', p.consultant_id, 'week', p.week_commencing, 'direction', p.direction, 'scope', p.duty_scope, 'priority', p.priority, 'notes', p.notes) order by p.week_commencing) from week_preferences p where p.workspace_id = w.id), '[]'::jsonb),
    'special', coalesce((select jsonb_object_agg(s.consultant_id, jsonb_build_object('weekend_mode', s.weekend_mode, 'notes', s.notes, 'partner_ids', coalesce((select jsonb_agg(sp.partner_id) from split_partner_preferences sp where sp.workspace_id = w.id and sp.consultant_id = s.consultant_id), '[]'::jsonb))) from consultant_period_settings s where s.workspace_id = w.id), '{}'::jsonb),
    'generation', jsonb_build_object('last_run', (select max(sr.run_at) from solver_runs sr where sr.workspace_id = w.id), 'status', coalesce((select sr.status from solver_runs sr where sr.workspace_id = w.id order by sr.run_at desc limit 1), 'Not generated'), 'assignments', coalesce((select jsonb_agg(jsonb_build_object('consultant_id', a.consultant_id, 'week', a.week_commencing, 'type', a.assignment_type, 'is_final', a.is_final)) from assignments a where a.workspace_id = w.id), '[]'::jsonb))
  ) end
  from (select p_workspace_id as id) requested
  left join rota_workspaces w on w.id = requested.id
  left join rota_periods rp on rp.workspace_id = w.id;
$$;

create or replace function public.save_rota_state(p_workspace_id text, p_state jsonb)
returns void
language plpgsql
security invoker
set search_path = public
as $$
declare item jsonb; consultant_key text; special_value jsonb; partner_value text;
begin
  insert into rota_workspaces(id) values (p_workspace_id)
  on conflict (id) do update set updated_at = now();
  insert into rota_periods(workspace_id, name, start_date, end_date, status)
  values (p_workspace_id, p_state#>>'{period,name}', (p_state#>>'{period,start}')::date, (p_state#>>'{period,end}')::date, coalesce(p_state#>>'{period,status}', 'Draft'))
  on conflict (workspace_id) do update set name=excluded.name, start_date=excluded.start_date, end_date=excluded.end_date, status=excluded.status, updated_at=now();

  delete from assignments where workspace_id=p_workspace_id;
  delete from solver_runs where workspace_id=p_workspace_id;
  delete from split_partner_preferences where workspace_id=p_workspace_id;
  delete from consultant_period_settings where workspace_id=p_workspace_id;
  delete from week_preferences where workspace_id=p_workspace_id;
  delete from absences where workspace_id=p_workspace_id;
  delete from workload_targets where workspace_id=p_workspace_id;
  delete from consultants where workspace_id=p_workspace_id;

  for item in select * from jsonb_array_elements(coalesce(p_state->'consultants','[]'::jsonb)) loop
    insert into consultants(id,workspace_id,name,email,active) values(item->>'id',p_workspace_id,item->>'name',coalesce(item->>'email',''),coalesce((item->>'active')::boolean,true));
  end loop;
  for consultant_key, item in select * from jsonb_each(coalesce(p_state->'targets','{}'::jsonb)) loop
    insert into workload_targets values(p_workspace_id,consultant_key,coalesce((item->>'t')::int,0),coalesce((item->>'weekend')::int,0),coalesce((item->>'c')::int,0));
  end loop;
  for item in select * from jsonb_array_elements(coalesce(p_state->'absences','[]'::jsonb)) loop
    insert into absences(id,workspace_id,consultant_id,absence_type,start_date,end_date,notes) values(item->>'id',p_workspace_id,item->>'consultant_id',item->>'type',(item->>'start')::date,(item->>'end')::date,coalesce(item->>'notes',''));
  end loop;
  for item in select * from jsonb_array_elements(coalesce(p_state->'preferences','[]'::jsonb)) loop
    insert into week_preferences(id,workspace_id,consultant_id,week_commencing,direction,duty_scope,priority,notes) values(item->>'id',p_workspace_id,item->>'consultant_id',(item->>'week')::date,item->>'direction',item->>'scope',item->>'priority',coalesce(item->>'notes',''));
  end loop;
  for consultant_key, special_value in select * from jsonb_each(coalesce(p_state->'special','{}'::jsonb)) loop
    insert into consultant_period_settings values(p_workspace_id,consultant_key,coalesce(special_value->>'weekend_mode','Standard'),coalesce(special_value->>'notes',''));
    for partner_value in select * from jsonb_array_elements_text(coalesce(special_value->'partner_ids','[]'::jsonb)) loop
      insert into split_partner_preferences values(p_workspace_id,consultant_key,partner_value);
    end loop;
  end loop;
  if nullif(p_state#>>'{generation,last_run}','') is not null then
    insert into solver_runs(workspace_id,run_at,status,payload) values(p_workspace_id,(p_state#>>'{generation,last_run}')::timestamptz,coalesce(p_state#>>'{generation,status}','Not generated'),'{}');
  end if;
end;
$$;

revoke all on function public.load_rota_state(text) from public, anon, authenticated;
revoke all on function public.save_rota_state(text,jsonb) from public, anon, authenticated;
grant execute on function public.load_rota_state(text) to service_role;
grant execute on function public.save_rota_state(text,jsonb) to service_role;
