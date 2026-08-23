-- Apply after schema.sql. Adds append-only solver drafts and audit-safe finalisation.
alter table public.solver_runs add column if not exists started_at timestamptz;
alter table public.solver_runs add column if not exists finished_at timestamptz;
alter table public.solver_runs add column if not exists solver_version text;
alter table public.solver_runs add column if not exists configuration jsonb not null default '{}'::jsonb;
alter table public.solver_runs add column if not exists runtime jsonb not null default '{}'::jsonb;
alter table public.solver_runs add column if not exists objective_value double precision;
alter table public.solver_runs add column if not exists error_message text;

create table if not exists public.rota_drafts (
  id bigint generated always as identity primary key,
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  solver_run_id bigint not null references public.solver_runs(id) on delete restrict,
  status text not null default 'Draft' check (status in ('Draft','Finalised','Rejected')),
  validation jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(), finalised_at timestamptz
);
alter table public.rota_drafts enable row level security;
alter table public.assignments add column if not exists draft_id bigint references public.rota_drafts(id) on delete cascade;
alter table public.assignments add column if not exists weekend_credit numeric(3,1) not null default 0;
alter table public.assignments alter column consultant_id drop not null;
alter table public.assignments drop constraint if exists assignments_assignment_type_check;
alter table public.assignments add constraint assignments_assignment_type_check
  check (assignment_type in ('C1','C2','T','STANDARD_WEEKEND','SPLIT_HALF_A','SPLIT_HALF_B'));
create index if not exists assignments_draft_idx on public.assignments(draft_id);

create or replace function public.finalise_rota_draft(p_workspace_id text, p_draft_id bigint)
returns void language plpgsql security invoker set search_path=public as $$
begin
  if exists (select 1 from rota_periods where workspace_id=p_workspace_id and status='Finalised') then raise exception 'This rota period is already finalised'; end if;
  if not exists (select 1 from rota_drafts where id=p_draft_id and workspace_id=p_workspace_id and validation='[]'::jsonb) then raise exception 'Draft does not exist or has validation errors'; end if;
  update rota_drafts set status='Finalised', finalised_at=now() where id=p_draft_id;
  update rota_periods set status='Finalised', updated_at=now() where workspace_id=p_workspace_id;
end; $$;
revoke all on function public.finalise_rota_draft(text,bigint) from public,anon,authenticated;
grant execute on function public.finalise_rota_draft(text,bigint) to service_role;

-- For an existing installation, remove the DELETE statements for assignments and
-- solver_runs from the legacy save_rota_state function before production use.
