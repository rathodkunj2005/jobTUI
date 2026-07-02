#!/usr/bin/env python3
"""
tracker.py — Kunj Rathod job search pipeline CLI.

Usage: python tracker.py <command> [options]

Commands:
  list        List companies (with optional filters)
  show        Show full details for one company
  update      Update status, URL, dates, notes, contact
  generate    Generate outreach message (referral/recruiter/alumni/linkedin)
  next        Show highest-priority next actions
  stats       Show funnel summary
  remind      Show (or send) email reminders
  last        Show last generated outreach message
  tui         Launch interactive curses TUI
  seed-links  Seed canonical careers URLs for companies with blank Job URL
  resume      Generate a personalized resume PDF for a company (via LLM)
"""
import argparse
import sys
from datetime import date
from pathlib import Path

# Add project dir to path so modules resolve when called from other dirs
sys.path.insert(0, str(Path(__file__).parent))

import config as cfg_module
import data
import outreach
import notify

# ── ANSI color helpers ────────────────────────────────────────────────────────

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def bold(t): return _c("1", t)
def green(t): return _c("32", t)
def yellow(t): return _c("33", t)
def red(t): return _c("31", t)
def cyan(t): return _c("36", t)
def dim(t): return _c("2", t)

STATUS_COLOR = {
    "Not Applied": dim,
    "Watching": dim,
    "Referral Pending": yellow,
    "Applied": cyan,
    "Phone Screen": green,
    "Onsite": green,
    "Offer": lambda t: _c("32;1", t),
    "Rejected": red,
    "Withdrawn": dim,
}

def _colorize_status(status: str) -> str:
    fn = STATUS_COLOR.get(status, str)
    return fn(status)

def _tier_label(app: data.Application) -> str:
    tier_colors = {1: cyan, 2: yellow, 3: dim}
    fn = tier_colors.get(app.tier_num, str)
    return fn(f"T{app.tier_num}{app.bucket}")

# ── Command implementations ───────────────────────────────────────────────────

def cmd_list(args) -> None:
    apps = data.load()
    filtered = data.filter_apps(
        apps,
        tier=args.tier,
        bucket=args.bucket,
        status=args.status,
        role_family=args.role_family,
    )
    filtered = filtered[: args.limit]

    if not filtered:
        print("No companies match that filter.")
        return

    print(bold(f"{'#':>3}  {'Tier':6} {'Score':5}  {'Company':<32} {'Status':<18} {'URL'}"))
    print("─" * 90)
    for i, app in enumerate(filtered, 1):
        url = app.job_url[:30] + "…" if len(app.job_url) > 31 else app.job_url
        print(
            f"{i:>3}  "
            f"{_tier_label(app):<14}  "
            f"{app.score:>5}  "
            f"{app.company:<32} "
            f"{_colorize_status(app.status):<18} "
            f"{dim(url)}"
        )
    print(dim(f"\n  {len(filtered)} companies shown"))


def cmd_show(args) -> None:
    apps = data.load()
    app = data.find(apps, args.company)
    if not app:
        print(red(f"Company not found: '{args.company}'"))
        sys.exit(1)

    sep = "─" * 60
    print(sep)
    print(bold(app.company))
    print(sep)
    print(f"  Tier / Bucket / Rank : {app.tier} | {app.bucket} | {app.rank}")
    print(f"  Role Family          : {app.role_family}")
    print(f"  Focus                : {app.focus}")
    print(f"  Resume Variant       : {app.resume}")
    print(f"  Scores               : SWE={app.swe_fit} AI={app.aiml_fit} Ref={app.referral_likelihood} Comp={app.comp_upside} Real={app.realism}  →  {bold(app.score)}")
    print(f"  Application Strategy : {app.strategy}")
    print(f"  Status               : {_colorize_status(app.status)}")
    print(f"  Contact              : {app.contact_name or dim('(none)')}")
    print(f"  Date Found           : {app.date_found or dim('(none)')}")
    print(f"  Date Applied         : {app.date_applied or dim('(none)')}")
    print(f"  Follow-up Date       : {app.followup_date or dim('(none)')}")
    print(f"  Job URL              : {app.job_url or dim('(none)')}")
    if app.notes:
        print(f"  Notes                : {app.notes}")
    print(sep)


def cmd_update(args) -> None:
    apps = data.load()
    app = data.find(apps, args.company)
    if not app:
        print(red(f"Company not found: '{args.company}'"))
        sys.exit(1)

    changed = []
    if args.status:
        if args.status not in data.STATUSES:
            print(yellow(f"Warning: '{args.status}' is not a recognized status."))
            print(f"  Valid: {', '.join(data.STATUSES)}")
        app.status = args.status
        changed.append(f"status → {args.status}")
    if args.notes:
        app.notes = args.notes
        changed.append("notes updated")
    if args.url:
        app.job_url = args.url
        changed.append(f"job_url → {args.url}")
    if args.date_applied:
        app.date_applied = args.date_applied
        changed.append(f"date_applied → {args.date_applied}")
    if args.date_found:
        app.date_found = args.date_found
        changed.append(f"date_found → {args.date_found}")
    if args.followup:
        app.followup_date = args.followup
        changed.append(f"followup_date → {args.followup}")
    if args.contact:
        app.contact_name = args.contact
        changed.append(f"contact → {args.contact}")
    if args.append_notes:
        sep = " | " if app.notes else ""
        app.notes = app.notes + sep + args.append_notes
        changed.append("notes appended")

    if not changed:
        print(yellow("Nothing to update. Pass at least one flag (--status, --url, etc.)."))
        return

    data.save(apps)
    print(green(f"Updated {app.company}:"))
    for c in changed:
        print(f"  {c}")


def cmd_generate(args) -> None:
    apps = data.load()
    app = data.find(apps, args.company)
    if not app:
        print(red(f"Company not found: '{args.company}'"))
        sys.exit(1)

    cfg = cfg_module.load()
    subject, body = outreach.generate(
        app=app,
        msg_type=args.msg_type,
        contact=args.contact,
        role=args.role,
        team=args.team,
        cfg=cfg,
    )

    outreach.save_last_prompt(
        company=app.company,
        msg_type=args.msg_type,
        contact=args.contact,
        role=args.role,
        subject=subject,
        body=body,
    )

    print("─" * 60)
    print(bold(f"Type    : {args.msg_type.upper()}"))
    print(bold(f"Company : {app.company}"))
    if args.contact:
        print(bold(f"To      : {args.contact}"))
    print("─" * 60)
    print(bold(f"Subject : {subject}"))
    print()
    print(body)
    print("─" * 60)
    print(dim("(Saved to prompts/last_prompt.json)"))


def cmd_next(args) -> None:
    apps = data.load()
    top = data.next_actions(apps, limit=args.limit)
    overdue = data.overdue_followups(apps)

    if overdue:
        print(bold(red(f"⚠  OVERDUE FOLLOW-UPS ({len(overdue)})")))
        for app in overdue:
            print(f"  {app.company:<32}  follow-up: {app.followup_date}  status: {_colorize_status(app.status)}")
        print()

    print(bold(f"Next {len(top)} actionable companies (by tier + score):"))
    print(f"{'#':>3}  {'Tier':6}  {'Score':5}  {'Company':<32}  {'Strategy':<35}  {'Resume'}")
    print("─" * 100)
    for i, app in enumerate(top, 1):
        print(
            f"{i:>3}  "
            f"{_tier_label(app):<14}  "
            f"{app.score:>5}  "
            f"{app.company:<32}  "
            f"{app.strategy[:35]:<35}  "
            f"Variant {app.resume}"
        )

    today = date.today()
    day_name = today.strftime("%A")
    print()
    print(dim(f"Today is {day_name}, {today}. Recommended cadence:"))
    cadence = {
        "Monday": "Review Tier 1 openings, pick 3 priority roles, customize resume.",
        "Tuesday": "Submit 2 Tier 1 apps + 5 referral/outreach messages.",
        "Wednesday": "Submit 1 Tier 1 + 2 Tier 2 apps. Log responses.",
        "Thursday": "Submit 3 Tier 2 apps + 5 more outreach messages.",
        "Friday": "Submit 2 Tier 3 or opportunistic apps. Follow up on prior outreach.",
        "Saturday": "90-min interview prep block: DS&A + systems + AI/ML fundamentals.",
        "Sunday": "Refresh tracker, review funnel metrics, prep next week.",
    }
    print(dim(f"  → {cadence.get(day_name, 'Review your tracker and outreach queue.')}"))


def cmd_stats(args) -> None:
    apps = data.load()
    total = len(apps)
    by_status: dict[str, int] = {}
    by_tier: dict[int, int] = {}
    applied = 0

    for app in apps:
        by_status[app.status] = by_status.get(app.status, 0) + 1
        by_tier[app.tier_num] = by_tier.get(app.tier_num, 0) + 1
        if app.status not in ("Not Applied", "Watching"):
            applied += 1

    print(bold("=== Application Funnel ==="))
    print(f"  Total companies tracked : {total}")
    print(f"  Action taken            : {applied}  ({100*applied//total if total else 0}%)")
    print()
    print(bold("  By Status:"))
    for status in data.STATUSES:
        count = by_status.get(status, 0)
        bar = "█" * count
        print(f"    {status:<20} {count:>3}  {dim(bar)}")
    print()
    print(bold("  By Tier:"))
    for tier_num in sorted(by_tier):
        count = by_tier[tier_num]
        done = sum(
            1 for a in apps
            if a.tier_num == tier_num and a.status not in ("Not Applied", "Watching")
        )
        print(f"    Tier {tier_num}  {count:>3} companies  {done} acted on")


def cmd_remind(args) -> None:
    apps = data.load()
    if args.send:
        cfg = cfg_module.load()
        notify.send_reminders(apps, cfg)
    else:
        notify.show_reminders(apps)
        print(dim("\n  (Pass --send to email these reminders via SMTP.)"))


def cmd_tui(args) -> None:
    from tui import run_tui
    run_tui()


def cmd_tamagotchi(args) -> None:
    import tamagotchi
    apps = data.load()
    state = tamagotchi._load_state()
    if args.once:
        tamagotchi.run_once(apps, state)
    else:
        tamagotchi.run_interactive(apps, state)


def cmd_listings(args) -> None:
    import job_fetcher
    apps = data.load()
    if args.company:
        target = data.find(apps, args.company)
        if not target:
            print(red(f"Company not found: {args.company}"))
            sys.exit(1)
        apps = [target]
    if args.list:
        cached = job_fetcher.load_cache()
        q = (args.filter or "").lower()
        for app in apps:
            entry = cached.get(app.company, {})
            jobs = entry.get("listings", [])
            if q and q not in app.company.lower():
                continue
            if not jobs:
                continue
            print(bold(f"{app.company}") + dim(f"  [{entry.get('ats','?')}]  {len(jobs)} roles"))
            for j in jobs[:5]:
                loc = j.get("location", "")
                print(f"  • {j['title'][:65]:<65}  {dim(loc)}")
            if len(jobs) > 5:
                print(dim(f"  … {len(jobs) - 5} more"))
            print()
    else:
        job_fetcher.main()


def cmd_seed_links(args) -> None:
    from seed_links import seed_links, unknown_companies
    updated = seed_links(dry_run=args.dry_run, force=args.force)

    if not updated:
        print(yellow("Nothing to update — all known companies already have URLs or no matches found."))
    else:
        verb = "Would update" if args.dry_run else "Updated"
        print(bold(f"{verb} {len(updated)} companies:"))
        for company, url in updated:
            print(f"  {company:<48} {dim(url)}")
        if args.dry_run:
            print(dim("\n  (Dry run — re-run without --dry-run to apply.)"))
        else:
            print(green(f"\n  Saved to {data.CSV_PATH}"))

    unknown = unknown_companies()
    if unknown:
        print(dim(f"\n  {len(unknown)} companies have no known URL entry (not modified):"))
        for co in unknown:
            print(dim(f"    {co}"))


def cmd_resume(args) -> None:
    apps = data.load()
    app = data.find(apps, args.company)
    if not app:
        print(red(f"Company not found: '{args.company}'"))
        sys.exit(1)

    import resume_gen
    cfg = cfg_module.load()

    print(f"Generating resume for {bold(app.company)} (variant {app.resume or 'A'})…")
    if app.job_url:
        print(dim(f"  Fetching job description from: {app.job_url[:70]}"))
    else:
        print(dim("  No job URL set — tailoring by role family only."))

    try:
        pdf_path = resume_gen.generate_resume(app, cfg)
    except Exception as exc:
        print(red(f"Error: {exc}"))
        sys.exit(1)

    print(green(f"PDF: {pdf_path}"))
    if not args.no_open:
        resume_gen.open_pdf(pdf_path)


def cmd_assess(args) -> None:
    apps = data.load()
    app = data.find(apps, args.company)
    if not app:
        print(red(f"Company not found: '{args.company}'"))
        sys.exit(1)

    import resume_fit
    resume_path = args.resume if args.resume else None
    try:
        report = resume_fit.assess_resume_for_app(app, resume_path=resume_path)
        out = resume_fit.save_report(report)
    except Exception as exc:
        print(red(f"Error: {exc}"))
        sys.exit(1)

    print(report.to_markdown())
    print(green(f"Saved: {out}"))


def cmd_people(args) -> None:
    apps = data.load()
    app = data.find(apps, args.company)
    if not app:
        print(red(f"Company not found: '{args.company}'"))
        sys.exit(1)

    import subprocess
    import people_finder
    searches = people_finder.build_searches(app)
    print(people_finder.format_searches(app))
    if args.open:
        idx = max(1, min(args.open, len(searches))) - 1
        subprocess.run(["open", searches[idx].url], check=False)
        print(green(f"Opened: {searches[idx].label}"))


def cmd_last(args) -> None:
    prompt = outreach.load_last_prompt()
    if not prompt:
        print(yellow("No last prompt found. Run `generate` first."))
        return
    print("─" * 60)
    print(bold(f"Last generated: {prompt['timestamp']}"))
    print(bold(f"Company : {prompt['company']}"))
    print(bold(f"Type    : {prompt['type']}"))
    if prompt.get("contact"):
        print(bold(f"To      : {prompt['contact']}"))
    if prompt.get("role"):
        print(bold(f"Role    : {prompt['role']}"))
    print("─" * 60)
    print(bold(f"Subject : {prompt['subject']}"))
    print()
    print(prompt["body"])
    print("─" * 60)


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tracker",
        description="Kunj Rathod — job search pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    # list
    lp = sub.add_parser("list", help="List companies with optional filters")
    lp.add_argument("--tier", type=int, choices=[1, 2, 3], help="Filter by tier number")
    lp.add_argument("--bucket", choices=["A", "B", "C"], help="Filter by priority bucket")
    lp.add_argument("--status", metavar="STATUS", help="Filter by status (exact, case-insensitive)")
    lp.add_argument("--role-family", metavar="FAMILY", help="Filter by role family substring")
    lp.add_argument("--limit", type=int, default=50, metavar="N", help="Max rows to show (default 50)")

    # show
    sp = sub.add_parser("show", help="Show full details for one company")
    sp.add_argument("company", help="Company name (substring match)")

    # update
    up = sub.add_parser("update", help="Update a company's application data")
    up.add_argument("company", help="Company name (substring match)")
    up.add_argument("--status", help=f"New status. Choices: {', '.join(data.STATUSES)}")
    up.add_argument("--notes", help="Replace notes")
    up.add_argument("--append-notes", metavar="TEXT", help="Append to existing notes")
    up.add_argument("--url", help="Job posting URL")
    up.add_argument("--date-applied", metavar="YYYY-MM-DD", help="Date applied")
    up.add_argument("--date-found", metavar="YYYY-MM-DD", help="Date role was found")
    up.add_argument("--followup", metavar="YYYY-MM-DD", help="Follow-up reminder date")
    up.add_argument("--contact", help="Contact name for outreach")

    # generate
    gp = sub.add_parser("generate", help="Generate outreach message")
    gp.add_argument("company", help="Company name (substring match)")
    gp.add_argument(
        "--type", dest="msg_type",
        choices=["referral", "recruiter", "alumni", "linkedin"],
        required=True,
        help="Message type",
    )
    gp.add_argument("--contact", help="Contact/recipient name")
    gp.add_argument("--role", help="Role title")
    gp.add_argument("--team", help="Team name for context")

    # next
    np = sub.add_parser("next", help="Show next actionable companies + daily cadence tip")
    np.add_argument("--limit", type=int, default=15, metavar="N", help="Max items (default 15)")

    # stats
    sub.add_parser("stats", help="Show funnel statistics")

    # remind
    rp = sub.add_parser("remind", help="Show (or send) follow-up email reminders")
    rp.add_argument("--send", action="store_true", help="Actually send via SMTP (requires config)")

    # last
    sub.add_parser("last", help="Show the last generated outreach message")

    # tui
    sub.add_parser("tui", help="Launch interactive curses TUI (browse, inspect, generate outreach)")

    # seed-links
    slp = sub.add_parser("seed-links", help="Seed canonical careers URLs for companies with blank Job URL")
    slp.add_argument("--dry-run", action="store_true", help="Print changes without saving")
    slp.add_argument("--force", action="store_true", help="Overwrite URLs that are already set")

    # tamagotchi
    tp = sub.add_parser("tamagotchi", help="Show Appli, your job search health companion")
    tp.add_argument("--once", action="store_true", help="Print once and exit (no animation)")

    # resume
    rsp = sub.add_parser("resume", help="Generate a personalized resume PDF for a company")
    rsp.add_argument("company", help="Company name (substring match)")
    rsp.add_argument("--no-open", action="store_true", help="Don't open the PDF after generation")

    # assess
    ap = sub.add_parser("assess", help="Assess whether the current/latest resume can plausibly get an interview")
    ap.add_argument("company", help="Company name (substring match)")
    ap.add_argument("--resume", metavar="PATH", help="Resume PDF/TXT/MD/TEX path. Defaults to newest resume PDF under Kunj_Rathod_Resume")

    # people
    pp = sub.add_parser("people", help="Build safe LinkedIn people-search links for a tracked company")
    pp.add_argument("company", help="Company name (substring match)")
    pp.add_argument("--open", type=int, choices=[1, 2, 3, 4], metavar="N", help="Open one of the generated LinkedIn searches")

    # listings
    llp = sub.add_parser("listings", help="Fetch / show real open job listings for tracked companies")
    llp.add_argument("--list", action="store_true", help="Show cached listings (no fetch)")
    llp.add_argument("--force", action="store_true", help="Force full refresh from APIs")
    llp.add_argument("--company", metavar="NAME", help="Limit to one company")
    llp.add_argument("--filter", metavar="Q", help="Filter displayed companies by name")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "list": cmd_list,
        "show": cmd_show,
        "update": cmd_update,
        "generate": cmd_generate,
        "next": cmd_next,
        "stats": cmd_stats,
        "remind": cmd_remind,
        "last": cmd_last,
        "tui": cmd_tui,
        "seed-links": cmd_seed_links,
        "tamagotchi": cmd_tamagotchi,
        "listings": cmd_listings,
        "resume": cmd_resume,
        "assess": cmd_assess,
        "people": cmd_people,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
