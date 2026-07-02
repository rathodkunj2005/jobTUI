"""Resume ↔ job interview-fit assessment helpers.

This is intentionally local-first: extract text from a resume PDF/TXT, compare it
against the tracked job/company context, and produce a concise markdown report.
No fabricated odds, no pretending to know recruiter behavior — just evidence,
gaps, and next actions.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import data
import resume_gen

BASE_DIR = Path(__file__).parent
DEFAULT_RESUME_ROOT = BASE_DIR.parent
ASSESSMENTS_DIR = BASE_DIR / "data" / "assessments"

# Curated for Kunj's target lane: backend/platform/AI infra/FDE/new-grad SWE.
SKILL_KEYWORDS = [
    "python", "java", "typescript", "javascript", "go", "c++", "sql",
    "aws", "azure", "gcp", "kubernetes", "docker", "terraform", "linux",
    "distributed systems", "backend", "platform", "infrastructure", "microservices",
    "data pipeline", "spark", "hadoop", "postgres", "mongodb", "cassandra", "redis",
    "llm", "rag", "agent", "agents", "inference", "eval", "evaluation",
    "machine learning", "pytorch", "fine-tuning", "retrieval", "observability",
    "metrics", "latency", "scale", "security", "enterprise", "customer", "deployment",
]

STRONG_ACTIONS = [
    "shipped", "built", "owned", "designed", "deployed", "optimized", "scaled",
    "reduced", "improved", "automated", "launched", "integrated", "led",
]


@dataclass
class FitReport:
    company: str
    role_family: str
    resume_path: Path
    score: int
    verdict: str
    matched_keywords: list[str]
    missing_keywords: list[str]
    evidence: list[str]
    risks: list[str]
    next_actions: list[str]
    job_source: str

    def to_markdown(self) -> str:
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {x}" for x in items) if items else "- —"

        return f"""# Interview-fit assessment: {self.company}

Generated: {datetime.now().isoformat(timespec='seconds')}
Resume: `{self.resume_path}`
Role family: {self.role_family or '—'}
Job source: {self.job_source}

## Verdict
{self.verdict} — {self.score}/100

## Matched signals
{bullets(self.matched_keywords[:18])}

## Main gaps / risks
{bullets(self.risks)}

## Missing keywords to consider adding honestly
{bullets(self.missing_keywords[:12])}

## Evidence from current resume
{bullets(self.evidence)}

## Next actions before applying
{bullets(self.next_actions)}
"""


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "company"


def pick_latest_resume(root: str | Path = DEFAULT_RESUME_ROOT) -> Path:
    """Pick the newest likely resume file under root.

    Prefers PDFs with "resume" in the name, excluding generated date-stamped
    company-tailored outputs only when a non-generated candidate exists.
    """
    root = Path(root).expanduser()
    candidates = [p for p in root.rglob("*.pdf") if p.is_file() and "resume" in p.name.lower()]
    if not candidates:
        candidates = [p for p in root.rglob("*.pdf") if p.is_file()]
    if not candidates:
        raise FileNotFoundError(f"No resume PDF found under {root}")

    non_generated = [p for p in candidates if "/generated/" not in str(p)]
    pool = non_generated or candidates
    return max(pool, key=lambda p: (p.stat().st_mtime, p.name))


def extract_resume_text(path: str | Path) -> str:
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() in {".txt", ".md", ".tex"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Unsupported resume file type: {path.suffix}. Use PDF/TXT/MD/TEX.")

    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        with tempfile.TemporaryDirectory(prefix="resume_text_") as tmp:
            out = Path(tmp) / "resume.txt"
            result = subprocess.run([pdftotext, "-layout", str(path), str(out)], capture_output=True, text=True)
            if result.returncode == 0 and out.exists():
                return out.read_text(encoding="utf-8", errors="ignore")

    # Python fallback.
    try:
        from pypdf import PdfReader
    except Exception:
        from PyPDF2 import PdfReader  # type: ignore
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def keyword_match(resume_text: str, job_text: str) -> dict:
    resume_l = resume_text.lower()
    job_l = job_text.lower()
    relevant = [kw for kw in SKILL_KEYWORDS if kw in job_l]
    if not relevant:
        relevant = [kw for kw in SKILL_KEYWORDS if kw in resume_l][:20]
    matched = [kw for kw in relevant if kw in resume_l]
    missing = [kw for kw in relevant if kw not in resume_l]
    score = round(100 * len(matched) / max(1, len(relevant)))
    return {"keyword_score": score, "matched_keywords": matched, "missing_keywords": missing, "relevant_keywords": relevant}


def _extract_evidence(resume_text: str, matched: list[str]) -> list[str]:
    lines = [re.sub(r"\s+", " ", ln).strip(" •-\t") for ln in resume_text.splitlines()]
    lines = [ln for ln in lines if len(ln) > 45]
    scored: list[tuple[int, str]] = []
    for ln in lines:
        low = ln.lower()
        score = sum(2 for kw in matched if kw in low) + sum(1 for a in STRONG_ACTIONS if a in low)
        if score:
            scored.append((score, ln))
    scored.sort(key=lambda x: -x[0])
    seen = set()
    out = []
    for _, ln in scored:
        key = ln[:80]
        if key not in seen:
            seen.add(key)
            out.append(ln[:220])
        if len(out) >= 5:
            break
    return out


def _verdict(score: int) -> str:
    if score >= 78:
        return "Strong interview story"
    if score >= 60:
        return "Credible interview shot"
    if score >= 42:
        return "Stretch unless tailored"
    return "Weak fit with current resume"


def _job_text_for_app(app: data.Application, explicit_job_text: str = "") -> tuple[str, str]:
    if explicit_job_text:
        return explicit_job_text, "provided text"
    fetched = resume_gen.fetch_job_description(app.job_url)
    if fetched:
        return fetched, app.job_url or "job URL"
    fallback = "\n".join(x for x in [app.company, app.role_family, app.focus, app.strategy, app.notes] if x)
    return fallback, "tracker fields"


def assess_resume_for_app(app: data.Application, resume_path: str | Path | None = None, job_text: str = "") -> FitReport:
    resume_path = Path(resume_path).expanduser() if resume_path else pick_latest_resume()
    resume_text = extract_resume_text(resume_path)
    target_text, source = _job_text_for_app(app, job_text)
    match = keyword_match(resume_text, target_text)

    keyword_score = match["keyword_score"]
    resume_l = resume_text.lower()
    action_bonus = min(10, sum(1 for a in STRONG_ACTIONS if a in resume_l))
    role_bonus = 8 if (app.role_family and any(w in resume_l for w in app.role_family.lower().split() if len(w) > 3)) else 0
    score = max(0, min(100, round(keyword_score * 0.82 + action_bonus + role_bonus)))

    matched = match["matched_keywords"]
    missing = match["missing_keywords"]
    evidence = _extract_evidence(resume_text, matched)
    risks = []
    if score < 60:
        risks.append("Current resume does not surface enough of the job's explicit keywords/signals.")
    if len(evidence) < 3:
        risks.append("Few concrete bullets map cleanly to this posting; recruiter skim may miss the fit.")
    if missing:
        risks.append("Missing visible signals: " + ", ".join(missing[:8]))
    if not app.job_url:
        risks.append("No live job URL in tracker, so this is based on company/role context rather than a real posting.")

    next_actions = [
        "Tailor the top 3 bullets to mirror the job's strongest requirements without inventing claims.",
        "Add one project/experience bullet that proves production impact: scale, latency, reliability, cost, or users.",
        "Use the People search in the TUI to find 2 employees/recruiters before applying.",
    ]
    if missing:
        next_actions.insert(0, "If true, add these signals to the resume: " + ", ".join(missing[:6]))

    return FitReport(
        company=app.company,
        role_family=app.role_family,
        resume_path=resume_path,
        score=score,
        verdict=_verdict(score),
        matched_keywords=matched,
        missing_keywords=missing,
        evidence=evidence,
        risks=risks,
        next_actions=next_actions,
        job_source=source,
    )


def save_report(report: FitReport, out_dir: str | Path = ASSESSMENTS_DIR) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_slug(report.company)}_fit.md"
    path.write_text(report.to_markdown(), encoding="utf-8")
    return path
