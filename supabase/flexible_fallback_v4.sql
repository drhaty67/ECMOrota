-- Apply after schema.sql, integration_v2.sql and bank_holidays_v3.sql.
alter table public.solver_runs add column if not exists solve_mode text not null default 'STRICT'
  check (solve_mode in ('STRICT', 'FLEXIBLE_FALLBACK'));
alter table public.assignments add column if not exists t_block_credit numeric(4,2) not null default 0
  check (t_block_credit between 0 and 1);
alter table public.assignments add column if not exists flexible boolean not null default false;
