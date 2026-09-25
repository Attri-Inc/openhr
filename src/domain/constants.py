"""Pure domain constants — no I/O, no dependencies.

Policy lives here as *data*, not as branches: adding a leave type, an employment
status transition or a hiring stage is a dict/tuple edit, never an `if`.
"""

# Leave is counted in integer half-day units, the way money is counted in cents.
UNITS_PER_DAY: int = 2

# The leave catalogue. `tracked` types draw down an annual entitlement and can
# never go negative; untracked types are recorded but not rationed.
LEAVE_POLICY: dict[str, dict] = {
    "casual": {"name": "Casual Leave", "annual_quota_days": 12, "paid": True, "tracked": True},
    "sick": {"name": "Sick Leave", "annual_quota_days": 12, "paid": True, "tracked": True},
    "earned": {"name": "Earned Leave", "annual_quota_days": 18, "paid": True, "tracked": True},
    "comp": {"name": "Compensatory Off", "annual_quota_days": 0, "paid": True, "tracked": True},
    "wfh": {"name": "Work From Home", "annual_quota_days": 0, "paid": True, "tracked": False},
    "maternity": {
        "name": "Maternity Leave",
        "annual_quota_days": 0,
        "paid": True,
        "tracked": False,
    },
    "unpaid": {
        "name": "Leave Without Pay",
        "annual_quota_days": 0,
        "paid": False,
        "tracked": False,
    },
}

LEAVE_TYPES: frozenset[str] = frozenset(LEAVE_POLICY)
TRACKED_LEAVE_TYPES: frozenset[str] = frozenset(
    code for code, policy in LEAVE_POLICY.items() if policy["tracked"]
)

# A leave request's lifecycle. `pending` is the only state a decision may act on;
# `approved` may still be cancelled (which releases the reserved balance).
LEAVE_STATUSES: frozenset[str] = frozenset({"pending", "approved", "declined", "cancelled"})
LEAVE_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"approved", "declined", "cancelled"}),
    "approved": frozenset({"cancelled"}),
    "declined": frozenset(),
    "cancelled": frozenset(),
}
# Statuses that hold (reserve or consume) balance. Everything else releases it.
BALANCE_CONSUMING_STATUSES: frozenset[str] = frozenset({"pending", "approved"})

# Employment lifecycle as a state machine. `exited` is terminal.
EMPLOYMENT_STATUSES: frozenset[str] = frozenset({"probation", "active", "notice", "exited"})
EMPLOYMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "probation": frozenset({"active", "notice", "exited"}),
    "active": frozenset({"notice", "exited"}),
    "notice": frozenset({"exited", "active"}),  # a withdrawn resignation returns to active
    "exited": frozenset(),
}

EMPLOYMENT_TYPES: frozenset[str] = frozenset({"full_time", "part_time", "contract", "intern"})

# Hiring funnel, in order. A candidate advances one step at a time and never
# moves backwards; the terminal outcomes are reachable from any live stage.
CANDIDATE_STAGES: tuple[str, ...] = (
    "applied",
    "screening",
    "manager_round",
    "final_round",
    "offer",
    "hired",
)
TERMINAL_CANDIDATE_STAGES: frozenset[str] = frozenset({"hired", "rejected", "withdrawn"})
CANDIDATE_OUTCOMES: frozenset[str] = frozenset({"rejected", "withdrawn"})
ALL_CANDIDATE_STAGES: frozenset[str] = frozenset(CANDIDATE_STAGES) | CANDIDATE_OUTCOMES

REQUISITION_STATUSES: frozenset[str] = frozenset(
    {"draft", "pending", "approved", "on_hold", "closed"}
)

# Assets. `status` is derived from assignment state and never set by hand except
# for repair/retirement.
ASSET_STATUSES: frozenset[str] = frozenset({"in_stock", "assigned", "in_repair", "retired"})
ASSET_CONDITIONS: frozenset[str] = frozenset({"new", "good", "fair", "poor", "damaged"})

EXIT_STATUSES: frozenset[str] = frozenset(
    {"initiated", "clearance_pending", "completed", "withdrawn"}
)
EXIT_REASONS: frozenset[str] = frozenset(
    {"resignation", "termination", "end_of_contract", "retirement", "absconding"}
)

# The clearance gates an exit must pass before it can be completed. Data, not code.
EXIT_CLEARANCE_STEPS: tuple[str, ...] = (
    "assets_returned",
    "knowledge_transfer",
    "finance_settlement",
    "access_revoked",
    "exit_interview",
)

# The only employee columns a report may group by. Column names cannot be bound
# as SQL parameters, so this allowlist is what keeps `headcount_rows` safe.
HEADCOUNT_DIMENSIONS: frozenset[str] = frozenset(
    {"department", "location", "status", "employment_type", "band", "designation"}
)
