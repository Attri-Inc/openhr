-- OpenHR schema — the people warehouse.
--
-- Two conventions carry through every table:
--   * Leave is INTEGER half-day units (UNITS_PER_DAY = 2). Money is INTEGER
--     minor units (paise). There is no float column anywhere.
--   * History is append-only. A decided leave request, a returned asset
--     assignment and a completed exit are never rewritten; the columns that do
--     change (status, decided_at, returned_on) are set once, forward-only, and
--     every change writes an audit row in the same DB transaction.
--
-- NOTE: the balance invariant ("approved + pending units for a tracked leave
-- type never exceed the entitlement") is an APPLICATION invariant enforced in
-- LeaveService, not a DB constraint — SQLite cannot express it as a CHECK. Do
-- not bypass the service layer with raw INSERTs.

CREATE TABLE employees (
  id              TEXT PRIMARY KEY,
  code            TEXT NOT NULL UNIQUE,                 -- payroll code, e.g. PH-1042
  name            TEXT NOT NULL,
  email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
  phone           TEXT,
  department      TEXT NOT NULL,
  designation     TEXT NOT NULL,
  manager_id      TEXT REFERENCES employees(id) ON DELETE RESTRICT,
  location        TEXT,
  employment_type TEXT NOT NULL DEFAULT 'full_time'
                    CHECK (employment_type IN ('full_time','part_time','contract','intern')),
  band            TEXT,
  status          TEXT NOT NULL DEFAULT 'probation'
                    CHECK (status IN ('probation','active','notice','exited')),
  joined_on       TEXT NOT NULL,                        -- ISO date (YYYY-MM-DD)
  exited_on       TEXT,
  date_of_birth   TEXT,
  ctc_minor       INTEGER NOT NULL DEFAULT 0 CHECK (ctc_minor >= 0),
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  CHECK (manager_id IS NULL OR manager_id != id),       -- nobody reports to themselves
  CHECK (status != 'exited' OR exited_on IS NOT NULL),  -- an exit always has a date
  CHECK (exited_on IS NULL OR exited_on >= joined_on)
);
CREATE INDEX idx_employees_status ON employees(status);
CREATE INDEX idx_employees_dept ON employees(department);
CREATE INDEX idx_employees_manager ON employees(manager_id);

-- The annual bucket a tracked leave type draws down. One row per
-- (employee, type, leave year); comp-off is credited by raising entitled_units.
CREATE TABLE leave_entitlements (
  id             TEXT PRIMARY KEY,
  employee_id    TEXT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
  leave_type     TEXT NOT NULL,
  year           INTEGER NOT NULL,
  entitled_units INTEGER NOT NULL CHECK (entitled_units >= 0),
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  UNIQUE (employee_id, leave_type, year)
);

CREATE TABLE leave_requests (
  id            TEXT PRIMARY KEY,
  employee_id   TEXT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
  leave_type    TEXT NOT NULL,
  start_date    TEXT NOT NULL,                          -- ISO date
  end_date      TEXT NOT NULL,
  units         INTEGER NOT NULL CHECK (units > 0),     -- half-days
  reason        TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','approved','declined','cancelled')),
  requested_by  TEXT NOT NULL,
  decided_by    TEXT,
  decided_at    TEXT,
  decision_note TEXT,
  cancelled_at  TEXT,
  cancel_reason TEXT,
  created_at    TEXT NOT NULL,
  CHECK (end_date >= start_date),
  -- approved/declined always carry a decision stamp
  CHECK (status IN ('pending','cancelled') OR decided_at IS NOT NULL)
);
CREATE INDEX idx_leave_employee ON leave_requests(employee_id, leave_type);
CREATE INDEX idx_leave_status ON leave_requests(status);
CREATE INDEX idx_leave_dates ON leave_requests(start_date, end_date);

CREATE TABLE assets (
  id            TEXT PRIMARY KEY,
  tag           TEXT NOT NULL UNIQUE,                   -- internal asset tag
  name          TEXT NOT NULL,
  category      TEXT NOT NULL,
  serial_number TEXT UNIQUE,
  value_minor   INTEGER NOT NULL DEFAULT 0 CHECK (value_minor >= 0),
  condition     TEXT NOT NULL DEFAULT 'good'
                  CHECK (condition IN ('new','good','fair','poor','damaged')),
  status        TEXT NOT NULL DEFAULT 'in_stock'
                  CHECK (status IN ('in_stock','assigned','in_repair','retired')),
  location      TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
CREATE INDEX idx_assets_status ON assets(status);
CREATE INDEX idx_assets_category ON assets(category);

CREATE TABLE asset_assignments (
  id                 TEXT PRIMARY KEY,
  asset_id           TEXT NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
  employee_id        TEXT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
  issued_on          TEXT NOT NULL,
  issued_condition   TEXT NOT NULL
                       CHECK (issued_condition IN ('new','good','fair','poor','damaged')),
  returned_on        TEXT,
  returned_condition TEXT
                       CHECK (returned_condition IS NULL OR
                              returned_condition IN ('new','good','fair','poor','damaged')),
  note               TEXT,
  created_at         TEXT NOT NULL,
  CHECK (returned_on IS NULL OR returned_on >= issued_on),
  -- a return records both a date and a condition, or neither
  CHECK ((returned_on IS NULL AND returned_condition IS NULL)
      OR (returned_on IS NOT NULL AND returned_condition IS NOT NULL))
);
-- Custody invariant, enforced by the engine: an asset has at most ONE open
-- (unreturned) assignment at a time.
CREATE UNIQUE INDEX idx_assignment_open ON asset_assignments(asset_id) WHERE returned_on IS NULL;
CREATE INDEX idx_assignment_employee ON asset_assignments(employee_id);

CREATE TABLE documents (
  id          TEXT PRIMARY KEY,
  employee_id TEXT NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
  doc_group   TEXT NOT NULL,                            -- e.g. "Joining documents"
  name        TEXT NOT NULL,
  file_type   TEXT NOT NULL DEFAULT 'PDF',
  size_bytes  INTEGER NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
  uploaded_by TEXT NOT NULL,
  uploaded_at TEXT NOT NULL,
  UNIQUE (employee_id, doc_group, name)
);
CREATE INDEX idx_documents_employee ON documents(employee_id);

CREATE TABLE requisitions (
  id                TEXT PRIMARY KEY,                   -- e.g. MRF-2026-014
  title             TEXT NOT NULL,
  department        TEXT NOT NULL,
  positions         INTEGER NOT NULL CHECK (positions > 0),
  employment_type   TEXT NOT NULL DEFAULT 'full_time'
                      CHECK (employment_type IN ('full_time','part_time','contract','intern')),
  status            TEXT NOT NULL DEFAULT 'draft'
                      CHECK (status IN ('draft','pending','approved','on_hold','closed')),
  hiring_manager_id TEXT REFERENCES employees(id) ON DELETE RESTRICT,
  budget_min_minor  INTEGER CHECK (budget_min_minor IS NULL OR budget_min_minor >= 0),
  budget_max_minor  INTEGER CHECK (budget_max_minor IS NULL OR budget_max_minor >= 0),
  location          TEXT,
  work_mode         TEXT,
  target_date       TEXT,
  priority          TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high')),
  reason            TEXT,
  skills            TEXT,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  CHECK (budget_min_minor IS NULL OR budget_max_minor IS NULL
         OR budget_max_minor >= budget_min_minor)
);
CREATE INDEX idx_requisitions_status ON requisitions(status);

CREATE TABLE candidates (
  id                 TEXT PRIMARY KEY,
  requisition_id     TEXT NOT NULL REFERENCES requisitions(id) ON DELETE RESTRICT,
  name               TEXT NOT NULL,
  email              TEXT NOT NULL COLLATE NOCASE,
  phone              TEXT,
  source             TEXT,
  experience_years   INTEGER CHECK (experience_years IS NULL OR experience_years >= 0),
  current_ctc_minor  INTEGER CHECK (current_ctc_minor IS NULL OR current_ctc_minor >= 0),
  expected_ctc_minor INTEGER CHECK (expected_ctc_minor IS NULL OR expected_ctc_minor >= 0),
  notice_days        INTEGER CHECK (notice_days IS NULL OR notice_days >= 0),
  stage              TEXT NOT NULL DEFAULT 'applied'
                       CHECK (stage IN ('applied','screening','manager_round','final_round',
                                        'offer','hired','rejected','withdrawn')),
  location           TEXT,
  resume_file        TEXT,
  notes              TEXT,
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL,
  UNIQUE (requisition_id, email)
);
CREATE INDEX idx_candidates_stage ON candidates(stage);
CREATE INDEX idx_candidates_req ON candidates(requisition_id);

CREATE TABLE interviews (
  id             TEXT PRIMARY KEY,
  candidate_id   TEXT NOT NULL REFERENCES candidates(id) ON DELETE RESTRICT,
  round_no       INTEGER NOT NULL CHECK (round_no > 0),
  stage          TEXT NOT NULL,
  interviewer    TEXT NOT NULL,
  scheduled_at   TEXT NOT NULL,
  -- Score out of 5, stored as INTEGER TENTHS (45 = 4.5) so there is no float.
  score_tenths   INTEGER CHECK (score_tenths IS NULL OR (score_tenths BETWEEN 0 AND 50)),
  recommendation TEXT CHECK (recommendation IS NULL OR
                             recommendation IN ('strong_hire','hire','no_hire','strong_no_hire')),
  remarks        TEXT,
  created_at     TEXT NOT NULL,
  UNIQUE (candidate_id, round_no)
);

CREATE TABLE exits (
  id               TEXT PRIMARY KEY,
  employee_id      TEXT NOT NULL UNIQUE REFERENCES employees(id) ON DELETE RESTRICT,
  reason           TEXT NOT NULL
                     CHECK (reason IN ('resignation','termination','end_of_contract',
                                       'retirement','absconding')),
  resigned_on      TEXT NOT NULL,
  last_working_day TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'initiated'
                     CHECK (status IN ('initiated','clearance_pending','completed','withdrawn')),
  notes            TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  CHECK (last_working_day >= resigned_on)
);

CREATE TABLE exit_clearance (
  id      TEXT PRIMARY KEY,
  exit_id TEXT NOT NULL REFERENCES exits(id) ON DELETE RESTRICT,
  step    TEXT NOT NULL CHECK (step IN ('assets_returned','knowledge_transfer',
                                        'finance_settlement','access_revoked','exit_interview')),
  is_done INTEGER NOT NULL DEFAULT 0 CHECK (is_done IN (0,1)),
  done_by TEXT,
  done_at TEXT,
  note    TEXT,
  UNIQUE (exit_id, step),
  CHECK ((is_done = 0 AND done_at IS NULL) OR (is_done = 1 AND done_at IS NOT NULL))
);

CREATE TABLE holidays (
  id           TEXT PRIMARY KEY,
  holiday_date TEXT NOT NULL,
  name         TEXT NOT NULL,
  region       TEXT NOT NULL DEFAULT 'IN',
  is_optional  INTEGER NOT NULL DEFAULT 0 CHECK (is_optional IN (0,1)),
  UNIQUE (holiday_date, region)
);

CREATE TABLE audit_log (
  seq         INTEGER PRIMARY KEY AUTOINCREMENT,
  id          TEXT NOT NULL UNIQUE,
  actor       TEXT NOT NULL,
  action      TEXT NOT NULL,   -- create_employee, request_leave, decide_leave_request, ...
  object_type TEXT NOT NULL,
  object_id   TEXT,
  details     TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_audit_action ON audit_log(action);

CREATE TABLE org_settings (
  id                     INTEGER PRIMARY KEY CHECK (id = 1),
  company_name           TEXT NOT NULL,
  hr_email               TEXT NOT NULL,
  base_currency          TEXT NOT NULL DEFAULT 'INR',
  leave_year_start_month INTEGER NOT NULL DEFAULT 1
                           CHECK (leave_year_start_month BETWEEN 1 AND 12),
  notice_period_days     INTEGER NOT NULL DEFAULT 60 CHECK (notice_period_days >= 0),
  created_at             TEXT NOT NULL,
  updated_at             TEXT NOT NULL
);
