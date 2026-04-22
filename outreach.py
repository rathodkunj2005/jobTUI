"""Outreach message generation and last-prompt persistence."""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).parent
PROMPTS_DIR = BASE_DIR / "prompts"
LAST_PROMPT_FILE = PROMPTS_DIR / "last_prompt.json"

# ── Templates ─────────────────────────────────────────────────────────────────
# Based on linkedin_github_outreach.md — grounded in real candidate data.

_REFERRAL_SUBJECT = "Referral request for {role} at {company}"

_REFERRAL_BODY = """\
Hi {contact} —

I'm applying to {role} at {company} and wanted to reach out directly.

Quick context: I'm a University of Utah CS student graduating in Dec 2026, \
focused on AI/backend systems. Recent work includes a HIPAA-compliant Bedrock \
app for hospital leadership, legal-document RAG over 10M+ docs, biomedical \
GraphRAG over 1M+ entities, and a Microsoft Azure Data internship.

I think my background maps well to {team_or_focus}. If after a quick look \
you feel comfortable referring me, I'd really appreciate it. I can send the \
job link, resume, and 3 tailored bullets for the team.

Either way, thanks for considering it.

Kunj Rathod
{contact_line}"""

_RECRUITER_SUBJECT = "Candidate for SWE / ML systems roles — Kunj Rathod"

_RECRUITER_BODY = """\
Hi {contact} —

I'm reaching out for new-grad SWE/ML opportunities at {company}.

I'm a CS student at the University of Utah graduating in Dec 2026, \
with experience building production AI systems across healthcare, legal-tech, \
and knowledge-graph applications. Recent work includes:

  • HIPAA-compliant AI platform on AWS Bedrock for 90+ hospital executives
  • Legal-tech hybrid RAG over 10M+ documents and 5k+ daily queries
  • Biomedical GraphRAG over 1M+ entities with sub-500ms p95 retrieval
  • Microsoft Azure Data internship (current)

I'm specifically interested in backend, distributed systems, applied AI/ML \
infrastructure, and product-focused engineering roles{team_suffix}. If helpful, \
I can send a targeted resume and 2–3 relevant project summaries for open reqs.

Best,
Kunj Rathod
{contact_line}"""

_ALUMNI_SUBJECT = "Utah CS student interested in your path to {company}"

_ALUMNI_BODY = """\
Hi {contact} —

I'm Kunj Rathod, a CS student at the University of Utah recruiting for \
2026–2027 SWE/ML roles. I came across your profile while looking at Utah \
alumni at {company}.

My background is mostly in production AI systems: healthcare AI on AWS Bedrock, \
legal-tech RAG at scale, biomedical GraphRAG, and Microsoft Azure Data this cycle.

Your path into {company} looks closely aligned with where I'm trying to go. \
If you'd be open to it, I'd appreciate 15 minutes to learn what signals mattered \
most in your recruiting process and what teams I should pay attention to.

Thanks,
Kunj Rathod
{contact_line}"""

_LINKEDIN_BODY = """\
Hi {contact} — I'm Kunj Rathod, a CS student at the University of Utah \
(Dec 2026, AI/backend systems). Current Microsoft Azure Data intern with \
projects in healthcare AI, legal-tech RAG at scale, and biomedical GraphRAG. \
I'm targeting {role_or_focus} roles at {company} and would love a quick \
connection. Happy to share my resume or project links if useful."""

_TEAM_FOCUS_MAP = {
    "AI Systems": "distributed systems, backend infra, and applied AI/ML infrastructure",
    "Backend/AI Infra": "backend engineering, cloud infrastructure, and AI platform work",
    "Backend/Data Infra": "backend and distributed data infrastructure",
    "Backend/Infra": "backend systems and cloud infrastructure",
    "Backend/Platform": "backend engineering and platform infrastructure",
    "ML Systems": "ML systems, inference infrastructure, and systems engineering",
    "AI Platform": "AI/ML platform engineering and inference systems",
    "DevTools/Platform": "developer tools and platform engineering",
    "Retrieval/ML Infra": "retrieval systems, vector infrastructure, and ML engineering",
    "Platform/AI Infra": "platform engineering and AI infrastructure",
}


def _contact_line(cfg: dict) -> str:
    parts = []
    if cfg.get("phone"):
        parts.append(cfg["phone"])
    if cfg.get("email"):
        parts.append(cfg["email"])
    if cfg.get("linkedin"):
        parts.append(f"LinkedIn: {cfg['linkedin']}")
    if cfg.get("github"):
        parts.append(f"GitHub: {cfg['github']}")
    return " | ".join(parts) if parts else "[phone] | [email] | [LinkedIn] | [GitHub]"


def generate(
    app,  # Application dataclass
    msg_type: str,
    contact: Optional[str] = None,
    role: Optional[str] = None,
    team: Optional[str] = None,
    cfg: Optional[dict] = None,
) -> tuple[str, str]:
    """Return (subject, body) for the requested message type."""
    cfg = cfg or {}
    contact_str = contact or app.contact_name or "[Contact Name]"
    role_str = role or "Software Engineer / ML Systems Engineer"
    company = app.company
    team_or_focus = team or _TEAM_FOCUS_MAP.get(app.role_family, app.focus or "distributed systems and AI/ML infrastructure")
    cl = _contact_line(cfg)

    if msg_type == "referral":
        subject = _REFERRAL_SUBJECT.format(role=role_str, company=company)
        body = _REFERRAL_BODY.format(
            contact=contact_str,
            role=role_str,
            company=company,
            team_or_focus=team_or_focus,
            contact_line=cl,
        )
    elif msg_type == "recruiter":
        team_suffix = f" on the {team} team" if team else ""
        subject = _RECRUITER_SUBJECT
        body = _RECRUITER_BODY.format(
            contact=contact_str,
            company=company,
            team_suffix=team_suffix,
            contact_line=cl,
        )
    elif msg_type == "alumni":
        subject = _ALUMNI_SUBJECT.format(company=company)
        body = _ALUMNI_BODY.format(
            contact=contact_str,
            company=company,
            contact_line=cl,
        )
    elif msg_type == "linkedin":
        role_or_focus = role_str if role else app.role_family or app.focus
        subject = f"Connection request — {company}"
        body = _LINKEDIN_BODY.format(
            contact=contact_str,
            role_or_focus=role_or_focus,
            company=company,
        )
    else:
        raise ValueError(f"Unknown message type: {msg_type}")

    return subject, body


def save_last_prompt(
    company: str,
    msg_type: str,
    contact: Optional[str],
    role: Optional[str],
    subject: str,
    body: str,
) -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "timestamp": datetime.now().isoformat(),
        "company": company,
        "type": msg_type,
        "contact": contact,
        "role": role,
        "subject": subject,
        "body": body,
    }
    with open(LAST_PROMPT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_last_prompt() -> Optional[dict]:
    if not LAST_PROMPT_FILE.exists():
        return None
    with open(LAST_PROMPT_FILE, encoding="utf-8") as f:
        return json.load(f)
