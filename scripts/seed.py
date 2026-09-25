"""Seed a fresh OpenHR development database.

The dataset is the OpenHR Portal demo company (https://openhr-portal.vercel.app)
turned into real rows: nine people across five departments, their leave history
and balances, the kit they hold, three open requisitions with a live hiring
funnel, and one exit in progress.

Rows are inserted with direct SQL — the service layer is the write path for the
*application*, not for bootstrapping — but this script then re-checks the core
invariants through the services and fails loudly if the seeded data violates any
of them. A seed that cannot pass the app's own rules is a bug, not a fixture.

Usage: python scripts/seed.py    (re-running resets the database)
"""

import asyncio
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import DB_PATH  # noqa: E402
from src.domain.constants import (  # noqa: E402
    EXIT_CLEARANCE_STEPS,
    LEAVE_POLICY,
    TRACKED_LEAVE_TYPES,
    UNITS_PER_DAY,
)  # noqa: E402

SCHEMA = ROOT / "scripts" / "schema.sql"
NOW = datetime.now(UTC).isoformat()
YEAR = 2026


# Lakhs per annum -> integer paise. 1 lakh = 100,000 rupees = 10,000,000 paise.
def lpa(value_in_lakhs: str) -> int:
    whole, _, frac = value_in_lakhs.partition(".")
    tenths = int(whole) * 10 + (int(frac[0]) if frac else 0)
    return tenths * 1_000_000


def rupees(amount: int) -> int:
    return amount * 100


def days(count: float) -> int:
    return int(round(count * UNITS_PER_DAY))


# ---------------------------------------------------------------------------
# The demo company
# ---------------------------------------------------------------------------

# (id, code, name, email, phone, dept, designation, manager, location, type,
#  band, status, joined_on, dob, ctc_minor)
EMPLOYEES: list[tuple[Any, ...]] = [
    (
        "emp_priya",
        "PH-1001",
        "Priya Nair",
        "priya@openhr.com",
        "+91 98800 10001",
        "People",
        "Head of People",
        None,
        "Bengaluru",
        "full_time",
        "M5",
        "active",
        "2020-06-01",
        "1983-02-18",
        lpa("55.0"),
    ),
    (
        "emp_rohan",
        "PH-1003",
        "Rohan Mehta",
        "rohan@openhr.com",
        "+91 99012 44561",
        "Engineering",
        "VP Engineering",
        "emp_priya",
        "Bengaluru",
        "full_time",
        "M5",
        "active",
        "2021-01-07",
        "1985-09-03",
        lpa("68.0"),
    ),
    (
        "emp_karan",
        "PH-1015",
        "Karan Shah",
        "karan@openhr.com",
        "+91 98203 11876",
        "Finance",
        "Finance Controller",
        "emp_priya",
        "Mumbai",
        "full_time",
        "M3",
        "notice",
        "2021-11-22",
        "1986-09-05",
        lpa("38.0"),
    ),
    (
        "emp_aarav",
        "PH-1042",
        "Aarav Kapoor",
        "aarav@openhr.com",
        "+91 98450 22110",
        "Engineering",
        "Engineering Manager",
        "emp_rohan",
        "Bengaluru",
        "full_time",
        "M3",
        "active",
        "2022-03-12",
        "1988-09-14",
        lpa("42.0"),
    ),
    (
        "emp_sneha",
        "PH-1088",
        "Sneha Iyer",
        "sneha@openhr.com",
        "+91 90876 55412",
        "Design",
        "Senior Product Designer",
        "emp_aarav",
        "Remote · Kochi",
        "full_time",
        "IC4",
        "active",
        "2023-08-02",
        "1991-09-21",
        lpa("28.5"),
    ),
    (
        "emp_fatima",
        "PH-1121",
        "Fatima Sheikh",
        "fatima@openhr.com",
        "+91 88450 71234",
        "People",
        "Talent Acquisition Lead",
        "emp_priya",
        "Hyderabad",
        "full_time",
        "IC3",
        "active",
        "2024-04-15",
        "1992-09-09",
        lpa("22.0"),
    ),
    (
        "emp_dev",
        "PH-1203",
        "Dev Bhatia",
        "dev@openhr.com",
        "+91 77650 09912",
        "Engineering",
        "Backend Engineer II",
        "emp_aarav",
        "Pune",
        "full_time",
        "IC2",
        "active",
        "2025-02-03",
        "1996-09-27",
        lpa("19.5"),
    ),
    (
        "emp_meera",
        "PH-1240",
        "Meera Raghavan",
        "meera@openhr.com",
        "+91 96540 33120",
        "Finance",
        "Finance Analyst",
        "emp_karan",
        "Mumbai",
        "full_time",
        "IC2",
        "probation",
        "2025-05-19",
        "1997-09-11",
        lpa("14.0"),
    ),
    (
        "emp_tanvi",
        "PH-1266",
        "Tanvi Deshmukh",
        "tanvi@openhr.com",
        "+91 91234 55009",
        "Marketing",
        "Marketing Manager",
        "emp_fatima",
        "Remote · Nagpur",
        "full_time",
        "IC3",
        "probation",
        "2026-07-01",
        "1993-09-30",
        lpa("16.0"),
    ),
]

# Comp-off is credited, not granted by policy: these are the only balances that
# differ from the standard annual quota.
COMP_CREDITS = {"emp_dev": days(2), "emp_sneha": days(1)}

# (id, employee, type, start, end, days, reason, status, decided_by)
LEAVE: list[tuple[Any, ...]] = [
    (
        "lv_0001",
        "emp_sneha",
        "sick",
        "2026-09-15",
        "2026-09-16",
        2,
        "Viral fever, doctor advised rest",
        "approved",
        "emp_aarav",
    ),
    (
        "lv_0002",
        "emp_dev",
        "casual",
        "2026-09-15",
        "2026-09-15",
        1,
        "Family function in Pune",
        "approved",
        "emp_aarav",
    ),
    (
        "lv_0003",
        "emp_meera",
        "wfh",
        "2026-09-15",
        "2026-09-19",
        5,
        "Society maintenance work",
        "approved",
        "emp_karan",
    ),
    (
        "lv_0004",
        "emp_tanvi",
        "earned",
        "2026-09-22",
        "2026-09-26",
        5,
        "Pre-planned trip to Goa",
        "pending",
        None,
    ),
    (
        "lv_0005",
        "emp_dev",
        "comp",
        "2026-09-30",
        "2026-09-30",
        1,
        "Comp-off for release weekend",
        "pending",
        None,
    ),
    (
        "lv_0006",
        "emp_fatima",
        "casual",
        "2026-09-18",
        "2026-09-18",
        1,
        "Campus hiring drive travel buffer",
        "pending",
        None,
    ),
    (
        "lv_0007",
        "emp_sneha",
        "earned",
        "2026-08-04",
        "2026-08-08",
        5,
        "Annual family holiday",
        "approved",
        "emp_aarav",
    ),
    (
        "lv_0008",
        "emp_aarav",
        "casual",
        "2026-08-12",
        "2026-08-12",
        1,
        "Home loan documentation",
        "approved",
        "emp_rohan",
    ),
    (
        "lv_0009",
        "emp_rohan",
        "sick",
        "2026-07-28",
        "2026-07-29",
        2,
        "Food poisoning",
        "approved",
        "emp_priya",
    ),
    (
        "lv_0010",
        "emp_aarav",
        "earned",
        "2026-10-02",
        "2026-10-06",
        4,
        "Festive break with family",
        "pending",
        None,
    ),
    (
        "lv_0011",
        "emp_meera",
        "casual",
        "2026-06-11",
        "2026-06-11",
        0.5,
        "Half day — bank work",
        "approved",
        "emp_karan",
    ),
]

# (id, tag, name, category, serial, value_minor, condition, holder, issued_on)
ASSETS: list[tuple[Any, ...]] = [
    (
        "ast_0001",
        "AST-0001",
        'MacBook Pro 14" M3',
        "Laptop",
        "C02X9KJ1",
        rupees(189_000),
        "good",
        "emp_aarav",
        "2024-03-12",
    ),
    (
        "ast_0002",
        "AST-0002",
        'Dell UltraSharp 27"',
        "Monitor",
        "DLU27-4471",
        rupees(34_500),
        "good",
        "emp_aarav",
        "2024-03-12",
    ),
    (
        "ast_0003",
        "AST-0003",
        'MacBook Air 13" M2',
        "Laptop",
        "C02Y7LP0",
        rupees(112_000),
        "good",
        "emp_sneha",
        "2023-08-02",
    ),
    (
        "ast_0004",
        "AST-0004",
        "iPhone 14",
        "Phone",
        "F17GH8821",
        rupees(68_000),
        "fair",
        "emp_fatima",
        "2024-04-15",
    ),
    (
        "ast_0005",
        "AST-0005",
        "ThinkPad T14 Gen 4",
        "Laptop",
        "LT14-99120",
        rupees(98_000),
        "good",
        "emp_dev",
        "2025-02-03",
    ),
    (
        "ast_0006",
        "AST-0006",
        "Figma Org seat",
        "Software",
        "SEAT-0043",
        rupees(4_200),
        "new",
        "emp_sneha",
        "2023-08-02",
    ),
    (
        "ast_0007",
        "AST-0007",
        "Access card + HID fob",
        "Access",
        "HID-2210",
        rupees(1_500),
        "fair",
        "emp_karan",
        "2021-11-22",
    ),
    (
        "ast_0008",
        "AST-0008",
        "Logitech MX Keys",
        "Peripheral",
        "MXK-7712",
        rupees(9_400),
        "good",
        None,
        None,
    ),
]

DOCUMENTS: list[tuple[Any, ...]] = [
    ("emp_aarav", "Joining documents", "Signed offer letter", 491_520, "2022-03-12"),
    ("emp_aarav", "Joining documents", "NDA & IP assignment", 215_040, "2022-03-12"),
    ("emp_aarav", "Joining documents", "PAN + Aadhaar", 1_153_434, "2022-03-12"),
    ("emp_aarav", "Joining documents", "Previous relieving letter", 327_680, "2022-03-12"),
    ("emp_aarav", "Compensation & appraisal", "Appraisal letter FY25-26", 194_560, "2026-04-01"),
    ("emp_aarav", "Compensation & appraisal", "Promotion letter · M3", 179_200, "2025-04-01"),
    ("emp_aarav", "Compensation & appraisal", "ESOP grant letter", 266_240, "2024-06-18"),
    ("emp_aarav", "Compliance & policy", "POSH acknowledgement", 92_160, "2026-01-07"),
    ("emp_aarav", "Compliance & policy", "Handbook v4 sign-off", 112_640, "2026-01-07"),
    ("emp_sneha", "Joining documents", "Signed offer letter", 468_992, "2023-08-02"),
    ("emp_sneha", "Compliance & policy", "POSH acknowledgement", 92_160, "2026-01-07"),
    ("emp_dev", "Joining documents", "Signed offer letter", 455_680, "2025-02-03"),
    ("emp_dev", "Joining documents", "PAN + Aadhaar", 984_064, "2025-02-03"),
    ("emp_tanvi", "Joining documents", "Signed offer letter", 442_368, "2026-07-01"),
    ("emp_karan", "Joining documents", "Signed offer letter", 460_800, "2021-11-22"),
]

# (id, title, dept, positions, type, status, manager, budget_min, budget_max,
#  location, mode, target, priority, reason, skills)
REQUISITIONS: list[tuple[Any, ...]] = [
    (
        "MRF-2026-014",
        "Senior Frontend Engineer",
        "Engineering",
        2,
        "full_time",
        "approved",
        "emp_aarav",
        lpa("28.0"),
        lpa("34.0"),
        "Bengaluru",
        "Hybrid",
        "2026-10-31",
        "high",
        "Expansion",
        "React, TypeScript, design systems",
    ),
    (
        "MRF-2026-015",
        "HR Business Partner",
        "People",
        1,
        "full_time",
        "pending",
        "emp_priya",
        lpa("18.0"),
        lpa("22.0"),
        "Hyderabad",
        "Onsite",
        "2026-11-15",
        "medium",
        "New role",
        "HRBP, POSH, employee relations",
    ),
    (
        "MRF-2026-016",
        "Data Analyst (Contract)",
        "Finance",
        1,
        "contract",
        "pending",
        "emp_karan",
        rupees(140_000),
        rupees(140_000),
        "Mumbai",
        "Hybrid",
        "2026-10-01",
        "low",
        "Backfill",
        "SQL, Power BI, Excel",
    ),
]

# (id, requisition, name, email, phone, source, exp, current_ctc, expected_ctc,
#  notice_days, stage, location, resume, notes)
CANDIDATES: list[tuple[Any, ...]] = [
    (
        "cnd_0001",
        "MRF-2026-014",
        "Ishaan Verma",
        "ishaan.verma91@example.com",
        "919835871310",
        "Referral · Dev B.",
        7,
        lpa("24.0"),
        lpa("32.0"),
        30,
        "offer",
        "Bengaluru",
        "Naukri_IshaanVerma.pdf",
        "Negotiating on joining bonus. Has one competing offer, closes Friday.",
    ),
    (
        "cnd_0002",
        "MRF-2026-014",
        "Nikita Rao",
        "nikita.rao.dev@example.com",
        "919742210087",
        "LinkedIn",
        6,
        lpa("22.5"),
        lpa("29.0"),
        60,
        "final_round",
        "Remote",
        "NikitaRao_Frontend_2026.pdf",
        "Remote only — confirmed with Aarav that the role allows it.",
    ),
    (
        "cnd_0003",
        "MRF-2026-015",
        "Aditya Menon",
        "aditya.menon.hr@example.com",
        "918891220456",
        "Naukri",
        5,
        lpa("16.0"),
        lpa("20.0"),
        45,
        "manager_round",
        "Hyderabad",
        "AdityaMenon_HRBP.pdf",
        "Has handled POSH cases end to end — rare at this level.",
    ),
    (
        "cnd_0004",
        "MRF-2026-016",
        "Sara Qureshi",
        "sara.qureshi@example.com",
        "919820117745",
        "Agency · Zeta",
        4,
        rupees(110_000),
        rupees(130_000),
        15,
        "screening",
        "Mumbai",
        "Zeta_SaraQureshi_DA.pdf",
        "Agency fee 8.33% — Karan to approve before scheduling.",
    ),
    (
        "cnd_0005",
        "MRF-2026-014",
        "Vikram Patel",
        "vikram.patel.fe@example.com",
        "917766554433",
        "Careers page",
        8,
        lpa("30.0"),
        lpa("36.0"),
        90,
        "applied",
        "Pune",
        "VikramPatel_CV_Sept26.pdf",
        "Expectation is above band. Call only if Ishaan declines.",
    ),
    (
        "cnd_0006",
        "MRF-2026-015",
        "Leena Thomas",
        "leena.thomas88@example.com",
        "919447003321",
        "Referral · Fatima S.",
        6,
        lpa("17.5"),
        lpa("21.0"),
        60,
        "screening",
        "Kochi",
        "LeenaThomas_HRBP_2026.pdf",
        "Referred by Fatima — worked with her before at Zoho.",
    ),
]

# (candidate, round_no, stage, interviewer, when, sub-scores out of 5, recommendation, remarks)
INTERVIEWS: list[tuple[Any, ...]] = [
    (
        "cnd_0001",
        1,
        "screening",
        "Aarav Kapoor",
        "2026-08-24T11:00:00",
        [40, 45, 40, 40],
        "hire",
        "Strong on rendering performance, explained a real migration end to end.",
    ),
    (
        "cnd_0001",
        2,
        "manager_round",
        "Rohan Mehta",
        "2026-09-02T16:30:00",
        [40, 40, 35, 45],
        "hire",
        "Would hire. Asked good questions about on-call load.",
    ),
    (
        "cnd_0001",
        3,
        "final_round",
        "Priya Nair",
        "2026-09-09T18:00:00",
        [45, 40, 40, 45],
        "strong_hire",
        "Culture fit clear. Offer approved at band IC4.",
    ),
    (
        "cnd_0002",
        1,
        "screening",
        "Aarav Kapoor",
        "2026-08-29T15:00:00",
        [40, 40, 35, 40],
        "hire",
        "Clean fundamentals, good design sense. Push on system design next round.",
    ),
    (
        "cnd_0002",
        2,
        "manager_round",
        "Sneha Iyer",
        "2026-09-08T17:00:00",
        [45, 35, 40, 40],
        "hire",
        "Collaborates well with design. Wants clarity on career path.",
    ),
    (
        "cnd_0003",
        1,
        "screening",
        "Fatima Sheikh",
        "2026-09-05T14:00:00",
        [40, 35, 30, 40],
        "hire",
        "Good employee-relations instinct. Data comfort is average.",
    ),
    ("cnd_0006", 1, "screening", "Fatima Sheikh", "2026-09-18T12:00:00", None, None, None),
]

HOLIDAYS: list[tuple[Any, ...]] = [
    ("2026-01-01", "New Year's Day", 0),
    ("2026-01-26", "Republic Day", 0),
    ("2026-03-04", "Holi", 0),
    ("2026-04-14", "Dr. Ambedkar Jayanti", 1),
    ("2026-05-01", "May Day", 1),
    ("2026-08-15", "Independence Day", 0),
    ("2026-09-14", "Ganesh Chaturthi", 0),
    ("2026-10-02", "Gandhi Jayanti", 0),
    ("2026-10-20", "Dussehra", 0),
    ("2026-11-08", "Diwali", 0),
    ("2026-12-25", "Christmas Day", 0),
]

# Karan is on notice — the exit record and the employment status are seeded together.
EXIT: dict[str, Any] = {
    "id": "exit_0001",
    "employee_id": "emp_karan",
    "reason": "resignation",
    "resigned_on": "2026-09-01",
    "last_working_day": "2026-10-31",
    "status": "clearance_pending",
    "notes": "Moving to a CFO role at a Series B fintech. Replacement MRF not yet raised.",
    "done_steps": ("knowledge_transfer",),
}


# ---------------------------------------------------------------------------
# Insert
# ---------------------------------------------------------------------------


def build(conn: sqlite3.Connection) -> int:
    """Insert the whole dataset. Returns the number of audit rows written."""
    audit_rows: list[tuple[str, str, str, str]] = []

    def audit(action: str, object_type: str, object_id: str, details: str) -> None:
        audit_rows.append((action, object_type, object_id, details))

    conn.execute(
        "INSERT INTO org_settings (id, company_name, hr_email, base_currency, "
        "leave_year_start_month, notice_period_days, created_at, updated_at) "
        "VALUES (1, ?, ?, 'INR', 1, 60, ?, ?)",
        ("OpenHR Demo Pvt Ltd", "people@openhr.com", NOW, NOW),
    )

    for row in EMPLOYEES:
        (
            emp_id,
            code,
            name,
            email,
            phone,
            dept,
            designation,
            manager,
            location,
            emp_type,
            band,
            status,
            joined_on,
            dob,
            ctc,
        ) = row
        conn.execute(
            "INSERT INTO employees (id, code, name, email, phone, department, designation, "
            "manager_id, location, employment_type, band, status, joined_on, date_of_birth, "
            "ctc_minor, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                emp_id,
                code,
                name,
                email,
                phone,
                dept,
                designation,
                manager,
                location,
                emp_type,
                band,
                status,
                joined_on,
                dob,
                ctc,
                NOW,
                NOW,
            ),
        )
        audit("create_employee", "employee", emp_id, f"Seeded {code} · {name} — {designation}")

        for leave_type in sorted(TRACKED_LEAVE_TYPES):
            units = LEAVE_POLICY[leave_type]["annual_quota_days"] * UNITS_PER_DAY
            if leave_type == "comp":
                units = COMP_CREDITS.get(emp_id, 0)
            conn.execute(
                "INSERT INTO leave_entitlements (id, employee_id, leave_type, year, "
                "entitled_units, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (f"ent_{emp_id}_{leave_type}", emp_id, leave_type, YEAR, units, NOW, NOW),
            )

    for lv_id, emp_id, leave_type, start, end, day_count, reason, status, decider in LEAVE:
        decided_at = NOW if status in ("approved", "declined") else None
        conn.execute(
            "INSERT INTO leave_requests (id, employee_id, leave_type, start_date, end_date, "
            "units, reason, status, requested_by, decided_by, decided_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                lv_id,
                emp_id,
                leave_type,
                start,
                end,
                days(day_count),
                reason,
                status,
                emp_id,
                decider,
                decided_at,
                NOW,
            ),
        )
        audit(
            "request_leave",
            "leave_request",
            lv_id,
            f"{emp_id} {leave_type} {start}..{end} ({status})",
        )

    for ast_id, tag, name, category, serial, value, condition, holder, issued_on in ASSETS:
        status = "assigned" if holder else "in_stock"
        conn.execute(
            "INSERT INTO assets (id, tag, name, category, serial_number, value_minor, "
            "condition, status, location, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ast_id, tag, name, category, serial, value, condition, status, "Bengaluru", NOW, NOW),
        )
        if holder:
            assignment_id = f"asg_{ast_id.split('_')[1]}"
            conn.execute(
                "INSERT INTO asset_assignments (id, asset_id, employee_id, issued_on, "
                "issued_condition, created_at) VALUES (?,?,?,?,?,?)",
                (assignment_id, ast_id, holder, issued_on, condition, NOW),
            )
            audit("assign_asset", "asset", ast_id, f"{tag} · {name} issued to {holder}")

    for index, (emp_id, group, name, size, uploaded_on) in enumerate(DOCUMENTS, start=1):
        conn.execute(
            "INSERT INTO documents (id, employee_id, doc_group, name, file_type, size_bytes, "
            "uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                f"doc_{index:04d}",
                emp_id,
                group,
                name,
                "PDF",
                size,
                "emp_priya",
                f"{uploaded_on}T10:00:00+00:00",
            ),
        )

    for row in REQUISITIONS:
        conn.execute(
            "INSERT INTO requisitions (id, title, department, positions, employment_type, status, "
            "hiring_manager_id, budget_min_minor, budget_max_minor, location, work_mode, "
            "target_date, priority, reason, skills, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*row, NOW, NOW),
        )

    for row in CANDIDATES:
        conn.execute(
            "INSERT INTO candidates (id, requisition_id, name, email, phone, source, "
            "experience_years, current_ctc_minor, expected_ctc_minor, notice_days, stage, "
            "location, resume_file, notes, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (*row, NOW, NOW),
        )

    for index, (cand, round_no, stage, interviewer, when, scores, rec, remarks) in enumerate(
        INTERVIEWS, start=1
    ):
        # Average the sub-scores in integer tenths — no float anywhere.
        score_tenths = (sum(scores) + len(scores) // 2) // len(scores) if scores else None
        conn.execute(
            "INSERT INTO interviews (id, candidate_id, round_no, stage, interviewer, "
            "scheduled_at, score_tenths, recommendation, remarks, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"ivw_{index:04d}",
                cand,
                round_no,
                stage,
                interviewer,
                when,
                score_tenths,
                rec,
                remarks,
                NOW,
            ),
        )

    for index, (holiday_date, name, optional) in enumerate(HOLIDAYS, start=1):
        conn.execute(
            "INSERT INTO holidays (id, holiday_date, name, region, is_optional) "
            "VALUES (?,?,?,'IN',?)",
            (f"hol_{index:04d}", holiday_date, name, optional),
        )

    conn.execute(
        "INSERT INTO exits (id, employee_id, reason, resigned_on, last_working_day, status, "
        "notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            EXIT["id"],
            EXIT["employee_id"],
            EXIT["reason"],
            EXIT["resigned_on"],
            EXIT["last_working_day"],
            EXIT["status"],
            EXIT["notes"],
            NOW,
            NOW,
        ),
    )
    for step in EXIT_CLEARANCE_STEPS:
        done = step in EXIT["done_steps"]
        conn.execute(
            "INSERT INTO exit_clearance (id, exit_id, step, is_done, done_by, done_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                f"clr_{step}",
                EXIT["id"],
                step,
                1 if done else 0,
                "emp_priya" if done else None,
                NOW if done else None,
            ),
        )
    audit(
        "initiate_exit",
        "exit",
        EXIT["id"],
        f"Karan Shah — resignation, LWD {EXIT['last_working_day']}",
    )

    audit(
        "seed",
        "database",
        "openhr",
        f"Seeded {len(EMPLOYEES)} employees, {len(LEAVE)} leave requests, "
        f"{len(ASSETS)} assets, {len(CANDIDATES)} candidates",
    )

    for index, (action, object_type, object_id, details) in enumerate(audit_rows, start=1):
        conn.execute(
            "INSERT INTO audit_log (id, actor, action, object_type, object_id, details, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (f"aud_{index:04d}", "seed", action, object_type, object_id, details, NOW),
        )
    return len(audit_rows)


# ---------------------------------------------------------------------------
# Verify through the application's own rules
# ---------------------------------------------------------------------------


async def verify() -> list[str]:
    from src.container import container

    problems: list[str] = []
    try:
        employees = await container.employees.list_employees(include_exited=True)
        if len(employees) != len(EMPLOYEES):
            problems.append(f"expected {len(EMPLOYEES)} employees, found {len(employees)}")

        for employee in employees:
            balance = await container.leave.balance(employee["id"], YEAR)
            for entry in balance["balances"]:
                if entry["tracked"] and entry["available_units"] < 0:
                    problems.append(
                        f"{employee['code']} is overdrawn on {entry['leave_type']}: "
                        f"{entry['available']}"
                    )

        assets = await container.assets.list_assets()
        assigned = [a for a in assets["items"] if a["status"] == "assigned"]
        for asset in assigned:
            if not asset.get("holder_id"):
                problems.append(f"asset {asset['tag']} is 'assigned' with no open assignment")

        karan = await container.employees.get_employee("PH-1015")
        if not karan or karan["status"] != "notice":
            problems.append("Karan Shah should be on notice")
        checklist = await container.exits.checklist("PH-1015")
        if checklist["steps_total"] != len(EXIT_CLEARANCE_STEPS):
            problems.append("exit clearance checklist is incomplete")

        headcount = await container.reports.headcount("department")
        active = [e for e in employees if e["status"] != "exited"]
        if headcount["total_headcount"] != len(active):
            problems.append(
                f"headcount {headcount['total_headcount']} != {len(active)} non-exited employees"
            )
    finally:
        await container.close()
    return problems


def main() -> None:
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm", "-journal"):
        stale = Path(str(db_path) + suffix)
        if stale.exists():
            stale.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys=ON")
        audit_count = build(conn)
        conn.commit()
    finally:
        conn.close()

    problems = asyncio.run(verify())
    if problems:
        print("✗ Seed failed its own invariant checks:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)

    print(f"✓ Seeded {db_path}")
    print(
        f"  {len(EMPLOYEES)} employees · {len(LEAVE)} leave requests · {len(ASSETS)} assets · "
        f"{len(REQUISITIONS)} requisitions · {len(CANDIDATES)} candidates · "
        f"{len(INTERVIEWS)} interviews · {len(DOCUMENTS)} documents · "
        f"{len(HOLIDAYS)} holidays · 1 exit · {audit_count} audit rows"
    )


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
