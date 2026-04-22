# job_search — Kunj Rathod's local job search pipeline

A terminal-native pipeline for tracking applications, generating company-specific
outreach messages, and surfacing next actions. Zero external dependencies —
stdlib only.

---

## Setup

```bash
cd job_search/

# Optional: fill in your contact info for generated outreach signatures
cp config.example.ini config.ini
# Edit config.ini with your email, phone, LinkedIn, GitHub URLs

# Optional: env var alternative
cp .env.example .env
source .env
```

Python 3.10+ required. No `pip install` needed.

---

## Commands

Run all commands from the `job_search/` directory:

```
python tracker.py <command> [options]
```

### `list` — Browse companies

```bash
# All companies (default limit 50)
python tracker.py list

# Tier 1 only
python tracker.py list --tier 1

# Priority bucket A only
python tracker.py list --bucket A

# Not yet applied
python tracker.py list --status "Not Applied"

# Filter by role family
python tracker.py list --role-family "AI Systems"

# Combine filters
python tracker.py list --tier 1 --bucket A --status "Not Applied" --limit 20
```

### `show` — Company details

```bash
python tracker.py show Databricks
python tracker.py show "Anthropic"
python tracker.py show stripe        # case-insensitive substring match
```

### `update` — Update application data

```bash
# Mark as applied
python tracker.py update Databricks --status "Applied" --date-applied 2026-04-15

# Add job URL and contact
python tracker.py update Databricks --url "https://databricks.com/careers/..." --contact "Jane Smith"

# Set follow-up reminder
python tracker.py update Anthropic --followup 2026-04-22 --status "Applied"

# Add notes
python tracker.py update NVIDIA --notes "Applied via referral from John"
python tracker.py update NVIDIA --append-notes "Heard back from recruiter"
```

Valid statuses: `Not Applied`, `Watching`, `Referral Pending`, `Applied`,
`Phone Screen`, `Onsite`, `Offer`, `Rejected`, `Withdrawn`

### `generate` — Generate outreach messages

```bash
# Referral request
python tracker.py generate Databricks --type referral --contact "Alex Chen" --role "Backend Engineer"

# Recruiter cold outreach
python tracker.py generate "Snowflake" --type recruiter --contact "Sarah Lee" --team "Data Cloud Platform"

# Alumni message
python tracker.py generate Microsoft --type alumni --contact "Priya Sharma"

# LinkedIn connection request (short format)
python tracker.py generate Anthropic --type linkedin --contact "Research Engineer"
```

Output is printed to terminal. The message is also saved to `prompts/last_prompt.json`.

### `last` — Show last generated message

```bash
python tracker.py last
```

### `next` — Next actions + today's cadence

```bash
python tracker.py next
python tracker.py next --limit 20
```

Shows:
- Overdue follow-ups (if any)
- Top N actionable companies sorted by tier + weighted score
- Today's recommended cadence from the weekly application schedule

### `stats` — Funnel summary

```bash
python tracker.py stats
```

Shows application counts by status and by tier.

### `tui` — Interactive curses TUI

```bash
python tracker.py tui
```

Full-screen terminal UI. Navigate with keyboard — no mouse needed.

**Views:**

| Key | Action |
|-----|--------|
| `↑` / `↓` or `j` / `k` | Move through company list |
| `Enter` | Open detail view for selected company |
| `g` | Generate outreach (works in list or detail view) |
| `n` | Switch to Next Actions view |
| `s` | Switch to Stats / Funnel view |
| `/` | Enter filter mode (type to search by name, role, status, tier) |
| `ESC` | Clear filter / go back |
| `b` | Back to previous view |
| `e` | Open job URL in browser (detail view) |
| `c` | Copy outreach to clipboard (outreach view, uses pbcopy/xclip) |
| `r` | Reload data from CSV |
| `q` | Quit |

**Views:**
- **LIST** — Scrollable company table with tier color-coding and status highlights
- **DETAIL** — Full company info with all fields
- **OUTREACH** — Generated message preview; `c` copies to clipboard
- **NEXT** — Top 20 actionable companies + today's cadence tip
- **STATS** — Funnel breakdown by status and tier with inline bar charts

Requires a terminal ≥ 40×6. Resize handled gracefully.

---

### `seed-links` — Seed careers URLs

Fills blank `Job URL` fields with canonical careers-page URLs for all 85 tracked companies.

```bash
# Preview what would change (no file write)
python tracker.py seed-links --dry-run

# Apply: write careers URLs for all companies with a blank Job URL
python tracker.py seed-links

# Overwrite URLs that are already set (e.g. to reset to careers homepage)
python tracker.py seed-links --force
```

URLs point to each company's main careers/jobs landing page — not a specific requisition.
Use `update <company> --url <url>` to set a direct job-posting link once you find one.

---

### `remind` — Follow-up reminders

```bash
# Print reminder summary to terminal (safe, no email sent)
python tracker.py remind

# Send reminder email via SMTP (requires smtp config)
python tracker.py remind --send
```

Email is **never sent** without the explicit `--send` flag.

---

## Data file

All application data lives in `data/applications.csv`. You can edit it
directly in Excel/Numbers/any CSV editor — the CLI reads/writes the same file.

Column reference:
| Column | Description |
|---|---|
| Tier | Tier 1 / 2 / 3 |
| Priority Bucket | A (apply first) / B / C |
| Rank | Rank within tier |
| Company | Company name |
| Focus | Domain focus area |
| Role Family | Target role category |
| SWE Fit (1-5) | Backend/distributed systems fit |
| AI/ML Fit (1-5) | Inference/retrieval/agents fit |
| Referral Likelihood (1-5) | Realistic referral odds |
| Comp Upside (1-5) | Expected comp ceiling |
| Hiring Bar Realism (1-5) | Probability of clearing bar |
| Weighted Priority Score | 0.30*SWE + 0.25*AI + 0.15*Ref + 0.15*Comp + 0.15*Real |
| Resume Variant | A (AI systems) / B (cloud/backend) / C (devtools) |
| Application Strategy | Strategy note |
| Status | Current status |
| Notes | Free text |
| Job URL | Link to job posting |
| Date Found | YYYY-MM-DD |
| Date Applied | YYYY-MM-DD |
| Follow-up Date | YYYY-MM-DD — triggers overdue alert in `next` |
| Contact Name | Name for outreach personalization |

---

## Outreach message types

| Type | Use case |
|---|---|
| `referral` | Asking a connection at the company for a referral |
| `recruiter` | Cold outreach to a recruiter |
| `alumni` | Reaching out to a Utah/Microsoft alumni |
| `linkedin` | Short LinkedIn connection request note |

Templates are grounded in the candidate profile:
- University of Utah CS, Dec 2026
- Microsoft Azure Data intern
- HIPAA-compliant Bedrock healthcare AI platform
- Legal-tech hybrid RAG over 10M+ docs, 5k+ daily queries
- Biomedical GraphRAG over 1M+ entities, sub-500ms p95
- Multi-agent pipelines for materials science

---

## Config reference

`config.ini` (preferred) or environment variables (`TRACKER_*`):

```ini
[candidate]
name     = Kunj Rathod
email    = ...
phone    = ...
linkedin = ...
github   = ...

[smtp]
host = smtp.gmail.com
port = 587
user = ...
pass = ...       # Use Gmail App Password, not your main password
from = ...
to   = ...
```

Env var equivalents: `TRACKER_EMAIL`, `TRACKER_LINKEDIN`, `TRACKER_GITHUB`,
`TRACKER_SMTP_HOST`, `TRACKER_SMTP_PORT`, `TRACKER_SMTP_USER`,
`TRACKER_SMTP_PASS`, `TRACKER_NOTIFY_FROM`, `TRACKER_NOTIFY_TO`.

---

## Weekly cadence (from target_company_strategy.md)

| Day | Action |
|---|---|
| Monday | Review Tier 1 openings, pick 3 roles, customize resume |
| Tuesday | Submit 2 Tier 1 apps + 5 outreach messages |
| Wednesday | Submit 1 Tier 1 + 2 Tier 2 apps, log responses |
| Thursday | Submit 3 Tier 2 apps + 5 outreach messages |
| Friday | Submit 2 Tier 3 / opportunistic apps, follow up |
| Saturday | 90-min prep block: DS&A + systems + AI/ML |
| Sunday | Refresh tracker, prune targets, plan next week |

**6-week sprint target:** 18 Tier 1, 30–36 Tier 2, 12 Tier 3 apps, 50+ warm outreach.

---

## Files

```
job_search/
├── tracker.py            # Main CLI — all commands
├── tui.py                # Curses TUI (launched via tracker.py tui)
├── seed_links.py         # Careers URL seeder (launched via tracker.py seed-links)
├── data.py               # Data model + CSV I/O
├── outreach.py           # Outreach templates + last-prompt persistence
├── notify.py             # Email reminder logic
├── config.py             # Config loading (file + env vars)
├── data/
│   └── applications.csv  # Application tracker (85 companies)
├── prompts/
│   └── last_prompt.json  # Last generated outreach message
├── config.example.ini    # Sample config
├── .env.example          # Sample env vars
└── README.md             # This file
```
