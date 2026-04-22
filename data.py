"""Data model and CSV persistence for the application tracker."""
import csv
import re
from dataclasses import dataclass, field, fields, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
CSV_PATH = BASE_DIR / "data" / "applications.csv"

STATUSES = [
    "Not Applied",
    "Watching",
    "Referral Pending",
    "Applied",
    "Phone Screen",
    "Onsite",
    "Offer",
    "Rejected",
    "Withdrawn",
]

# Mapping from CSV header → dataclass field name
_HEADER_MAP = {
    "Tier": "tier",
    "Priority Bucket": "bucket",
    "Rank": "rank",
    "Company": "company",
    "Focus": "focus",
    "Role Family": "role_family",
    "SWE Fit (1-5)": "swe_fit",
    "AI/ML Fit (1-5)": "aiml_fit",
    "Referral Likelihood (1-5)": "referral_likelihood",
    "Comp Upside (1-5)": "comp_upside",
    "Hiring Bar Realism (1-5)": "realism",
    "Weighted Priority Score": "score",
    "Resume Variant": "resume",
    "Application Strategy": "strategy",
    "Status": "status",
    "Notes": "notes",
    "Job URL": "job_url",
    "Date Found": "date_found",
    "Date Applied": "date_applied",
    "Follow-up Date": "followup_date",
    "Contact Name": "contact_name",
}

_FIELD_TO_HEADER = {v: k for k, v in _HEADER_MAP.items()}

CSV_HEADERS = list(_HEADER_MAP.keys())


@dataclass
class Application:
    tier: str = ""
    bucket: str = ""
    rank: str = ""
    company: str = ""
    focus: str = ""
    role_family: str = ""
    swe_fit: str = ""
    aiml_fit: str = ""
    referral_likelihood: str = ""
    comp_upside: str = ""
    realism: str = ""
    score: str = ""
    resume: str = ""
    strategy: str = ""
    status: str = "Not Applied"
    notes: str = ""
    job_url: str = ""
    date_found: str = ""
    date_applied: str = ""
    followup_date: str = ""
    contact_name: str = ""

    @property
    def tier_num(self) -> int:
        m = re.search(r"\d+", self.tier)
        return int(m.group()) if m else 99

    @property
    def score_float(self) -> float:
        try:
            return float(self.score)
        except (ValueError, TypeError):
            return 0.0

    @property
    def is_actionable(self) -> bool:
        return self.status in ("Not Applied", "Watching", "Referral Pending")

    def to_row(self) -> dict:
        d = asdict(self)
        return {_FIELD_TO_HEADER[k]: v for k, v in d.items()}


def _row_to_app(row: dict) -> Application:
    kwargs = {}
    for header, field_name in _HEADER_MAP.items():
        kwargs[field_name] = row.get(header, "").strip()
    return Application(**kwargs)


def load() -> list[Application]:
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [_row_to_app(row) for row in reader]


def save(apps: list[Application]) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for app in apps:
            writer.writerow(app.to_row())


def find(apps: list[Application], query: str) -> Optional[Application]:
    """Case-insensitive substring match on company name."""
    q = query.lower().strip()
    # Exact match first
    for app in apps:
        if app.company.lower() == q:
            return app
    # Prefix match
    for app in apps:
        if app.company.lower().startswith(q):
            return app
    # Substring match
    for app in apps:
        if q in app.company.lower():
            return app
    return None


def filter_apps(
    apps: list[Application],
    tier: Optional[int] = None,
    bucket: Optional[str] = None,
    status: Optional[str] = None,
    role_family: Optional[str] = None,
) -> list[Application]:
    result = apps
    if tier is not None:
        result = [a for a in result if a.tier_num == tier]
    if bucket:
        result = [a for a in result if a.bucket.upper() == bucket.upper()]
    if status:
        result = [a for a in result if a.status.lower() == status.lower()]
    if role_family:
        result = [a for a in result if role_family.lower() in a.role_family.lower()]
    return result


def next_actions(apps: list[Application], limit: int = 15) -> list[Application]:
    """Return highest-priority actionable companies sorted by tier + score."""
    actionable = [a for a in apps if a.is_actionable]
    return sorted(actionable, key=lambda a: (a.tier_num, -a.score_float))[:limit]


def overdue_followups(apps: list[Application]) -> list[Application]:
    """Return applications with a follow-up date in the past."""
    today = date.today()
    result = []
    for app in apps:
        if not app.followup_date:
            continue
        try:
            fdate = datetime.strptime(app.followup_date, "%Y-%m-%d").date()
            if fdate <= today:
                result.append(app)
        except ValueError:
            pass
    return result
