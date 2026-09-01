-- Apply after schema.sql and integration_v2.sql.
create table if not exists public.bank_holidays (
  id text primary key,
  workspace_id text not null references public.rota_workspaces(id) on delete cascade,
  holiday_date date not null,
  name text not null default 'Bank holiday',
  created_at timestamptz not null default now(),
  unique (workspace_id, holiday_date),
  constraint bank_holiday_is_weekday check (extract(isodow from holiday_date) between 1 and 5)
);
create index if not exists bank_holidays_workspace_date_idx on public.bank_holidays(workspace_id, holiday_date);
alter table public.bank_holidays enable row level security;

alter table public.assignments add column if not exists c_day_credit integer not null default 0 check (c_day_credit between 0 and 3);
alter table public.assignments add column if not exists duty_dates jsonb not null default '[]'::jsonb;
