"""
resume_gen.py — Generate personalized LaTeX resumes for specific companies.

Tailors bullet points in the Experience and Projects sections based on the job
posting. Supports multiple LLM backends:
- Anthropic API key
- OpenAI API key
- Codex CLI using OpenAI/ChatGPT OAuth subscription login
- Claude Code CLI using Anthropic subscription login
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Constants ─────────────────────────────────────────────────────────────────

VARIANT_MAP = {
    "A": "top_ai_ml.tex",
    "B": "top_backend_infra.tex",
    "C": "top_swe.tex",
}

# Default if variant is missing or unrecognized
DEFAULT_VARIANT = "A"

PDFLATEX = "/Library/TeX/texbin/pdflatex"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "gpt-5.1"
DEFAULT_CODEX_MODEL = "gpt-5.1-codex"
DEFAULT_CLAUDE_CLI_MODEL = "sonnet"

_SYSTEM_PROMPT = """\
You are a LaTeX resume editor specializing in tailoring resumes for specific job applications.

Given a base LaTeX resume and information about a target role, your job is to rewrite ONLY
the bullet points (\\item lines) inside the Experience and Projects sections to best highlight
skills and experiences relevant to the job description.

Rules:
- Preserve ALL LaTeX commands, environments, preamble, and document structure exactly.
- Do NOT add, remove, or reorder sections, \\proj{}, \\role{}, \\subrole{}, or \\begin/\\end blocks.
- Do NOT change dates, company names, job titles, or contact information.
- Only rewrite the content of \\item lines within itemize/enumerate environments.
- Keep bullet count the same — do not add or remove bullets.
- Each bullet must remain factually grounded in the original content; do not invent metrics.
  You may emphasize, reframe, or reorder phrases to highlight relevance.
- Return ONLY the complete .tex file with no markdown fences, no commentary.
"""

# ── Gold standard detection ────────────────────────────────────────────────────

_DATE_SUFFIX = re.compile(r"_\d{8}\.tex$")


def find_gold_standards(output_dir: Path) -> list[Path]:
    """Return manually-curated gold-standard resume files in output_dir.

    Gold standards are files matching resume_*.tex that do NOT have a date
    suffix (e.g. resume_anthropic.tex, resume_nvidia_figure.tex).
    Date-stamped outputs like anthropic_20260423.tex are excluded.
    """
    return sorted(
        p for p in output_dir.glob("resume_*.tex")
        if not _DATE_SUFFIX.search(p.name)
    )


def pick_gold_standard(gold_files: list[Path], role_family: str, company: str) -> Path | None:
    """Choose the best gold standard for a given role/company by keyword matching.

    Scores each file against the role_family + company string using:
    1. The subtitle line in the LaTeX header (\\small\\color{gray2} <subtitle>)
    2. The filename stem (words split on underscore)

    Returns None if gold_files is empty.
    """
    if not gold_files:
        return None
    if len(gold_files) == 1:
        return gold_files[0]

    query = (role_family + " " + company).lower()
    query_words = {w for w in re.split(r"\W+", query) if len(w) > 3}

    scored: list[tuple[int, Path]] = []
    for gf in gold_files:
        try:
            content = gf.read_text()
        except Exception:
            scored.append((0, gf))
            continue
        # Extract subtitle from \small\color{gray2} <text>}
        subtitle_match = re.search(r"\\small\\color\{gray2\}\s+([^\}\\]+)", content)
        subtitle = subtitle_match.group(1).lower() if subtitle_match else ""
        stem_words = gf.stem.replace("_", " ").lower()
        scoring_text = subtitle + " " + stem_words
        score = sum(1 for w in query_words if w in scoring_text)
        scored.append((score, gf))

    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


# ── Core functions ─────────────────────────────────────────────────────────────

def fetch_job_description(url: str, timeout: int = 10) -> str:
    """Fetch visible text from a job URL. Returns up to 3000 chars."""
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:3000]
    except Exception:
        return ""


def load_base_template(variant: str, templates_dir: str, output_dir: Path | None = None,
                       role_family: str = "", company: str = "") -> tuple[str, str]:
    """Load the best-matching base template.

    Priority:
    1. Gold standards in output_dir (resume_*.tex, no date suffix) — picked by keyword match.
    2. Fallback: old top_*.tex files from templates_dir.

    Returns (tex_content, source_label) where source_label is the filename used.
    """
    # Try gold standards first
    if output_dir and output_dir.exists():
        golds = find_gold_standards(output_dir)
        best = pick_gold_standard(golds, role_family, company)
        if best:
            return best.read_text(), best.name

    # Fallback to old variant-mapped templates
    filename = VARIANT_MAP.get(variant.upper(), VARIANT_MAP[DEFAULT_VARIANT])
    path = Path(templates_dir) / filename
    if not path.exists():
        raise FileNotFoundError(
            f"No gold standards found in output_dir and no fallback template at {path}.\n"
            f"Add resume_*.tex gold standards to your output_dir, or set [resume] templates_dir "
            f"to the directory containing {', '.join(VARIANT_MAP.values())}."
        )
    return path.read_text(), filename


def _job_context(company: str, role_family: str, job_description: str) -> str:
    context = f"Role: {role_family} at {company}"
    if job_description:
        context += f"\n\nJob Description:\n{job_description}"
    else:
        context += "\n\n(No job description available — tailor for the company/role type.)"
    return context


def _user_prompt(base_tex: str, company: str, role_family: str, job_description: str) -> str:
    return (
        f"Base Resume:\n{base_tex}\n\n"
        f"{_job_context(company, role_family, job_description)}\n\n"
        "Return the tailored .tex file:"
    )


def _clean_tex_response(text: str) -> str:
    """Remove common CLI/API wrappers while preserving the LaTeX document."""
    text = (text or "").strip()
    fence = re.fullmatch(r"```(?:tex|latex)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    start = text.find("\\documentclass")
    if start > 0:
        text = text[start:].strip()

    end_doc = text.rfind("\\end{document}")
    if end_doc != -1:
        text = text[: end_doc + len("\\end{document}")].strip()

    if "\\documentclass" not in text or "\\end{document}" not in text:
        raise RuntimeError("LLM did not return a complete LaTeX document")
    return text


def _extract_anthropic_text(response) -> str:
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text" and getattr(block, "text", None):
            parts.append(block.text)
    if not parts:
        raise RuntimeError("Anthropic API returned no text blocks")
    return "\n".join(parts)


def _call_anthropic_api(base_tex: str, company: str, role_family: str,
                        job_description: str, api_key: str, model: str) -> str:
    """Call Anthropic API to tailor resume bullets. Uses prompt caching."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model or DEFAULT_ANTHROPIC_MODEL,
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    # Cache the base template — it's static per variant
                    {
                        "type": "text",
                        "text": f"Base Resume:\n{base_tex}",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": f"{_job_context(company, role_family, job_description)}\n\nReturn the tailored .tex file:",
                    },
                ],
            }
        ],
    )
    return _clean_tex_response(_extract_anthropic_text(response))


def _call_openai_api(base_tex: str, company: str, role_family: str,
                     job_description: str, api_key: str, model: str) -> str:
    """Call OpenAI API. Requires OPENAI_API_KEY or [resume] openai_api_key."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    prompt = _user_prompt(base_tex, company, role_family, job_description)
    model = model or DEFAULT_OPENAI_MODEL

    # Prefer Responses API when available; fall back to Chat Completions for older SDKs.
    if hasattr(client, "responses"):
        response = client.responses.create(
            model=model,
            instructions=_SYSTEM_PROMPT,
            input=prompt,
            max_output_tokens=8192,
        )
        text = getattr(response, "output_text", None)
        if not text:
            chunks = []
            for item in getattr(response, "output", []) or []:
                for content in getattr(item, "content", []) or []:
                    if getattr(content, "type", None) in {"output_text", "text"}:
                        chunks.append(getattr(content, "text", ""))
            text = "\n".join(chunks)
    else:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=8192,
        )
        text = response.choices[0].message.content

    return _clean_tex_response(text)


def _run_cli(command: list[str], prompt: str, timeout: int = 300, output_file: Path | None = None) -> str:
    result = subprocess.run(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr_tail = "\n".join((result.stderr or result.stdout).splitlines()[-30:])
        raise RuntimeError(f"{' '.join(command[:2])} failed (exit {result.returncode}):\n{stderr_tail}")

    if output_file and output_file.exists():
        return output_file.read_text()
    return result.stdout


def _call_codex_cli(base_tex: str, company: str, role_family: str,
                    job_description: str, model: str) -> str:
    """Use Codex CLI with the user's OpenAI/ChatGPT OAuth login."""
    if not shutil.which("codex"):
        raise RuntimeError("Codex CLI not found. Install it or choose provider=openai/anthropic/claude_cli.")

    prompt = _SYSTEM_PROMPT + "\n\n" + _user_prompt(base_tex, company, role_family, job_description)
    # If config omits model, let Codex use the user's configured/default model.
    with tempfile.TemporaryDirectory(prefix="resume_codex_") as tmp:
        out = Path(tmp) / "tailored.tex"
        cmd = [
            "codex", "exec",
            "--skip-git-repo-check",
            "--sandbox", "read-only",
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--output-last-message", str(out), "-"])
        text = _run_cli(cmd, prompt, output_file=out)
    return _clean_tex_response(text)


def _call_claude_cli(base_tex: str, company: str, role_family: str,
                     job_description: str, model: str) -> str:
    """Use Claude Code CLI with the user's Anthropic subscription login."""
    if not shutil.which("claude"):
        raise RuntimeError("Claude Code CLI not found. Install it or choose provider=anthropic/openai/codex_cli.")

    prompt = _user_prompt(base_tex, company, role_family, job_description)
    model = model or DEFAULT_CLAUDE_CLI_MODEL
    text = _run_cli(
        [
            "claude", "--print",
            "--model", model,
            "--system-prompt", _SYSTEM_PROMPT,
            "--no-session-persistence",
        ],
        prompt,
    )
    return _clean_tex_response(text)


def _resolve_provider(cfg: dict) -> str:
    provider = (cfg.get("resume_provider") or "auto").strip().lower().replace("-", "_")
    aliases = {
        "anthropic_api": "anthropic",
        "claude_api": "anthropic",
        "openai_api": "openai",
        "codex": "codex_cli",
        "openai_oauth": "codex_cli",
        "chatgpt": "codex_cli",
        "claude": "claude_cli",
        "anthropic_subscription": "claude_cli",
    }
    provider = aliases.get(provider, provider)
    if provider != "auto":
        return provider

    # Auto prefers explicit API keys, then subscription-backed CLIs.
    if cfg.get("resume_anthropic_api_key") or cfg.get("resume_api_key"):
        return "anthropic"
    if cfg.get("resume_openai_api_key"):
        return "openai"
    if shutil.which("codex"):
        return "codex_cli"
    if shutil.which("claude"):
        return "claude_cli"
    return "anthropic"


def _tailor_resume(base_tex: str, company: str, role_family: str,
                   job_description: str, cfg: dict) -> str:
    provider = _resolve_provider(cfg)
    model = (cfg.get("resume_model") or "").strip()

    if provider == "anthropic":
        api_key = cfg.get("resume_anthropic_api_key") or cfg.get("resume_api_key") or ""
        if not api_key:
            raise ValueError(
                "Anthropic API key not configured. Either add [resume] anthropic_api_key, "
                "set ANTHROPIC_API_KEY, or use provider=claude_cli for Anthropic subscription login."
            )
        return _call_anthropic_api(base_tex, company, role_family, job_description, api_key, model)

    if provider == "openai":
        api_key = cfg.get("resume_openai_api_key") or ""
        if not api_key:
            raise ValueError(
                "OpenAI API key not configured. Either add [resume] openai_api_key, "
                "set OPENAI_API_KEY, or use provider=codex_cli for OpenAI OAuth/subscription login."
            )
        return _call_openai_api(base_tex, company, role_family, job_description, api_key, model)

    if provider == "codex_cli":
        return _call_codex_cli(base_tex, company, role_family, job_description, model)

    if provider == "claude_cli":
        return _call_claude_cli(base_tex, company, role_family, job_description, model)

    raise ValueError("Unknown resume provider: %s. Use auto, anthropic, openai, codex_cli, or claude_cli." % provider)


def generate_resume(app, cfg: dict) -> Path:
    """
    Generate a personalized resume PDF for the given application.

    Returns the Path to the compiled PDF.
    Raises on missing config, missing template, provider failure, or pdflatex failure.
    """
    templates_dir = cfg.get("resume_templates_dir", "")
    if not templates_dir:
        raise ValueError(
            "Resume templates directory not configured.\n"
            "Add [resume] templates_dir = /path/to/resume/dir to config.ini"
        )

    output_dir = Path(cfg.get("resume_output_dir", str(Path(templates_dir) / "generated")))
    output_dir.mkdir(parents=True, exist_ok=True)

    variant = (app.resume or DEFAULT_VARIANT).strip().upper()
    if variant not in VARIANT_MAP:
        variant = DEFAULT_VARIANT

    role_family = app.role_family or app.focus or "Software Engineering"
    base_tex, template_name = load_base_template(
        variant, templates_dir,
        output_dir=output_dir,
        role_family=role_family,
        company=app.company,
    )
    print(f"  Base template: {template_name}")

    job_description = fetch_job_description(app.job_url)

    tailored_tex = _tailor_resume(
        base_tex=base_tex,
        company=app.company,
        role_family=role_family,
        job_description=job_description,
        cfg=cfg,
    )

    company_slug = re.sub(r"[^a-z0-9]+", "_", app.company.lower()).strip("_")
    today_str = date.today().strftime("%Y%m%d")
    tex_path = output_dir / f"{company_slug}_{today_str}.tex"
    tex_path.write_text(tailored_tex)

    pdf_path = _compile_pdf(tex_path, output_dir)
    return pdf_path


def _compile_pdf(tex_path: Path, output_dir: Path) -> Path:
    """Run pdflatex on tex_path; return path to the resulting PDF."""
    pdflatex = shutil.which("pdflatex") or (PDFLATEX if Path(PDFLATEX).exists() else None)
    if not pdflatex:
        raise RuntimeError("pdflatex not found. Install MacTeX/TeX Live or add pdflatex to PATH.")

    result = subprocess.run(
        [pdflatex, "-interaction=nonstopmode", "-output-directory", str(output_dir), str(tex_path)],
        capture_output=True,
        text=True,
    )
    pdf_path = output_dir / tex_path.with_suffix(".pdf").name
    if result.returncode != 0 and not pdf_path.exists():
        # Surface the last 20 lines of pdflatex output for diagnosis
        log_tail = "\n".join(result.stdout.splitlines()[-20:])
        raise RuntimeError(f"pdflatex failed (exit {result.returncode}):\n{log_tail}")
    return pdf_path


def open_pdf(path: Path) -> None:
    """Open PDF with the default macOS viewer."""
    subprocess.Popen(["open", str(path)])


# ── CLI entry point (for quick testing) ──────────────────────────────────────

if __name__ == "__main__":
    import config as cfg_module
    import data as data_mod

    if len(sys.argv) < 2:
        print("Usage: python resume_gen.py <company>")
        sys.exit(1)

    apps = data_mod.load()
    app = data_mod.find(apps, sys.argv[1])
    if not app:
        print(f"Company not found: {sys.argv[1]}")
        sys.exit(1)

    cfg = cfg_module.load()
    print(f"Generating resume for {app.company} (variant {app.resume})…")
    pdf = generate_resume(app, cfg)
    print(f"PDF: {pdf}")
    open_pdf(pdf)
