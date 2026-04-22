"""Email reminders for follow-ups. Dry-run by default; --send to actually send."""
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from data import Application, overdue_followups, next_actions  # noqa: E402


def build_reminder_text(overdue: list[Application], upcoming: list[Application]) -> str:
    lines = ["=== Job Search Reminders ===", f"Date: {date.today()}", ""]

    if overdue:
        lines.append(f"OVERDUE FOLLOW-UPS ({len(overdue)})")
        lines.append("-" * 40)
        for app in overdue:
            lines.append(f"  {app.company:30s}  follow-up: {app.followup_date}  status: {app.status}")
        lines.append("")

    if upcoming:
        lines.append(f"UPCOMING ACTIONS — highest priority not applied ({len(upcoming)})")
        lines.append("-" * 40)
        for app in upcoming:
            lines.append(f"  Tier {app.tier_num} | {app.bucket} | {app.company:30s} | score: {app.score}")
        lines.append("")

    if not overdue and not upcoming:
        lines.append("No pending reminders.")

    return "\n".join(lines)


def show_reminders(apps: list[Application], top_n: int = 10) -> str:
    overdue = overdue_followups(apps)
    top = next_actions(apps, limit=top_n)
    text = build_reminder_text(overdue, top)
    print(text)
    return text


def send_reminders(apps: list[Application], cfg: dict, top_n: int = 10) -> None:
    required = ["smtp_host", "smtp_user", "smtp_pass", "notify_to", "notify_from"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"[notify] Cannot send — missing config keys: {', '.join(missing)}")
        print("  Set them in config.ini [smtp] or via TRACKER_SMTP_* env vars.")
        return

    overdue = overdue_followups(apps)
    top = next_actions(apps, limit=top_n)
    body = build_reminder_text(overdue, top)

    msg = EmailMessage()
    msg["Subject"] = f"Job search reminders — {date.today()}"
    msg["From"] = cfg["notify_from"]
    msg["To"] = cfg["notify_to"]
    msg.set_content(body)

    try:
        port = int(cfg.get("smtp_port", 587))
        with smtplib.SMTP(cfg["smtp_host"], port) as server:
            server.starttls()
            server.login(cfg["smtp_user"], cfg["smtp_pass"])
            server.send_message(msg)
        print(f"[notify] Reminder email sent to {cfg['notify_to']}")
    except Exception as e:
        print(f"[notify] Failed to send email: {e}")
