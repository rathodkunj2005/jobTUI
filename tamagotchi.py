#!/usr/bin/env python3
"""
tamagotchi.py — Appli, your job search companion.

Run daily to check your application health and get motivated.
Appli gets hungrier the longer you go without applying.

Usage:
  python tamagotchi.py          # interactive mode (animated)
  python tamagotchi.py --once   # print once and exit (good for cron)
  python tamagotchi.py --feed   # mark today as a manual check-in
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
import data as data_mod

BASE_DIR   = Path(__file__).parent
STATE_FILE = BASE_DIR / "data" / "tamagotchi.json"

# ── ANSI helpers ──────────────────────────────────────────────────────────────

def _c(code, text):  return f"\033[{code}m{text}\033[0m"
def bold(t):         return _c("1", t)
def dim(t):          return _c("2", t)
def red(t):          return _c("31", t)
def yellow(t):       return _c("33", t)
def green(t):        return _c("32", t)
def cyan(t):         return _c("36", t)
def magenta(t):      return _c("35", t)
def clr():           return "\033[2J\033[H"
def hide_cursor():   print("\033[?25l", end="", flush=True)
def show_cursor():   print("\033[?25h", end="", flush=True)

# ── ASCII art ─────────────────────────────────────────────────────────────────
# Each state has two animation frames (A, B) and a color function.

CREATURES = {
    "thriving": {
        "color": green,
        "a": [
            r"  \(≧▽≦)/  ",
            r"   ( 💼 )   ",
            r"   /    \   ",
        ],
        "b": [
            r"  \(≧▽≦)/  ",
            r"   ( 💼 )   ",
            r"  //    \\  ",
        ],
        "face": "(≧▽≦)",
        "mood": "THRIVING",
        "msg": [
            "You're on a roll! Keep applying!",
            "The offers are coming. Don't stop!",
            "This is the energy. Let's get it.",
        ],
    },
    "happy": {
        "color": cyan,
        "a": [
            r"   (^‿^)    ",
            r"   ( 💼 )   ",
            r"   /    \   ",
        ],
        "b": [
            r"   (^‿^)    ",
            r"  -(💼)-   ",
            r"   /    \   ",
        ],
        "face": "(^‿^)",
        "mood": "HAPPY",
        "msg": [
            "Applied today! Appli is pleased.",
            "Good work. Stay consistent.",
            "One more today?",
        ],
    },
    "okay": {
        "color": yellow,
        "a": [
            r"   (•_•)    ",
            r"   (💼)    ",
            r"   |    |   ",
        ],
        "b": [
            r"   (•_•)    ",
            r"   (💼)    ",
            r"    |  |    ",
        ],
        "face": "(•_•)",
        "mood": "HUNGRY",
        "msg": [
            "Haven't eaten since yesterday...",
            "It's been a couple days. Apply today.",
            "Appli is getting restless.",
        ],
    },
    "hungry": {
        "color": yellow,
        "a": [
            r"   (>_<)    ",
            r"   ( ; )    ",
            r"    | |     ",
        ],
        "b": [
            r"   (>_<)    ",
            r"  -( ; )-   ",
            r"    | |     ",
        ],
        "face": "(>_<)",
        "mood": "HUNGRY!",
        "msg": [
            "Please... a single application...",
            "3+ days without applying. Fix this.",
            "Appli is shaking from hunger.",
        ],
    },
    "starving": {
        "color": red,
        "a": [
            r"   (╥_╥)   ",
            r"    ( ; )   ",
            r"     |      ",
        ],
        "b": [
            r"  . (╥_╥)  ",
            r"    ( ; )   ",
            r"     |      ",
        ],
        "face": "(╥_╥)",
        "mood": "STARVING",
        "msg": [
            "A week without applying. Appli is suffering.",
            "This is not okay. Open the TUI right now.",
            "The job market doesn't wait. Neither should you.",
        ],
    },
    "critical": {
        "color": red,
        "a": [
            r"  (✖﹏✖)   ",
            r"    \‸/     ",
            r"     |      ",
        ],
        "b": [
            r" .(✖﹏✖).  ",
            r"    \‸/     ",
            r"     |      ",
        ],
        "face": "(✖﹏✖)",
        "mood": "CRITICAL",
        "msg": [
            "Two weeks. This is a crisis.",
            "Appli may not survive much longer.",
            "Open the TUI. Apply. Now. Please.",
        ],
    },
    "dead": {
        "color": dim,
        "a": [
            r"  (✕_✕)    ",
            r"   (   )    ",
            r"  ━━━━━━━   ",
        ],
        "b": [
            r"  (✕_✕)    ",
            r"   (   )    ",
            r"  ━━━━━━━   ",
        ],
        "face": "(✕_✕)",
        "mood": "☠  EXPIRED",
        "msg": [
            "Appli has perished. Can you still revive it?",
            "Recruiters are moving on. Resuscitate Appli.",
            "Ghost of Appli: please... apply...",
        ],
    },
}


def _hunger_state(hunger_days: Optional[int]) -> str:
    if hunger_days is None:
        return "critical"  # never applied
    if hunger_days == 0:
        return "happy"
    if hunger_days == 1:
        return "okay"
    if hunger_days <= 4:
        return "hungry"
    if hunger_days <= 7:
        return "starving"
    if hunger_days <= 14:
        return "critical"
    return "dead"


def _thriving_check(hunger_days: Optional[int], applied_today: int) -> bool:
    return hunger_days == 0 and applied_today >= 2


# ── State file ────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"first_run": date.today().isoformat(), "name": "Appli"}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Stats computation ─────────────────────────────────────────────────────────

def compute_stats(apps: list) -> dict:
    today = date.today()
    today_str = today.isoformat()

    applied_dates = sorted(
        (a.date_applied for a in apps if a.date_applied),
        reverse=True,
    )
    total_applied = sum(1 for a in apps if a.status not in ("Not Applied", "Watching"))
    applied_today = sum(1 for a in apps if a.date_applied == today_str)
    in_flight     = sum(1 for a in apps if a.status in ("Applied", "Phone Screen", "Onsite"))
    offers        = sum(1 for a in apps if a.status == "Offer")
    overdue       = len(data_mod.overdue_followups(apps))
    not_applied   = sum(1 for a in apps if a.status in ("Not Applied", "Watching"))

    # Streak: consecutive days with at least one application
    streak = 0
    check = today
    applied_set = set(applied_dates)
    while check.isoformat() in applied_set:
        streak += 1
        check -= timedelta(days=1)

    # Hunger: days since last application
    if applied_dates:
        last_applied = date.fromisoformat(applied_dates[0])
        hunger_days = (today - last_applied).days
    else:
        hunger_days = None  # never fed

    return {
        "today": today_str,
        "hunger_days": hunger_days,
        "applied_today": applied_today,
        "total_applied": total_applied,
        "total": len(apps),
        "in_flight": in_flight,
        "offers": offers,
        "overdue": overdue,
        "not_applied": not_applied,
        "streak": streak,
        "last_applied": applied_dates[0] if applied_dates else None,
    }


# ── Bar helpers ───────────────────────────────────────────────────────────────

def _bar(filled: int, total: int, width: int = 18, full_char="█", empty_char="░") -> str:
    f = min(width, round(width * filled / total)) if total else 0
    return full_char * f + empty_char * (width - f)


def _hunger_bar(hunger_days: Optional[int], width: int = 18) -> str:
    if hunger_days is None:
        return "█" * width  # full hunger
    capped = min(hunger_days, 14)
    filled = round(width * capped / 14)
    bar = "█" * filled + "░" * (width - filled)
    return bar


# ── Render ────────────────────────────────────────────────────────────────────

def _hunger_label(hunger_days: Optional[int]) -> str:
    if hunger_days is None:
        return "never fed"
    if hunger_days == 0:
        return "fed today ✓"
    if hunger_days == 1:
        return "1 day ago"
    return f"{hunger_days} days starving"


def render(stats: dict, tui_state: dict, frame: int = 0, terminal_width: int = 60) -> str:
    hunger_days   = stats["hunger_days"]
    applied_today = stats["applied_today"]

    if _thriving_check(hunger_days, applied_today):
        state_key = "thriving"
    else:
        state_key = _hunger_state(hunger_days)

    creature = CREATURES[state_key]
    color_fn = creature["color"]
    art = creature["a"] if frame % 2 == 0 else creature["b"]
    msg = creature["msg"][frame % len(creature["msg"])]

    day_num = (date.today() - date.fromisoformat(tui_state.get("first_run", date.today().isoformat()))).days + 1
    name = tui_state.get("name", "Appli")

    W = min(terminal_width, 62)
    border = "═" * (W - 2)

    today = date.today()
    day_name = today.strftime("%A")
    cadence = {
        "Monday":    "Review T1 openings → pick 3 roles → customize.",
        "Tuesday":   "Submit 2 T1 apps + 5 outreach messages.",
        "Wednesday": "Submit 1 T1 + 2 T2 apps. Log responses.",
        "Thursday":  "Submit 3 T2 apps + 5 outreach messages.",
        "Friday":    "Submit 2 T3 apps. Follow up on prior outreach.",
        "Saturday":  "90-min prep: DS&A + systems + AI/ML.",
        "Sunday":    "Refresh tracker. Review metrics. Plan next week.",
    }
    today_goal = cadence.get(day_name, "Review tracker.")

    applied_b = _bar(stats["total_applied"], stats["total"])

    # Streak fire indicator
    streak = stats["streak"]
    streak_str = f"{'🔥' * min(streak, 5)} {streak}d" if streak > 0 else "0d"

    mood_label = creature["mood"]

    lines = [
        f"╔{border}╗",
        f"║  {bold(f'{name}  ·  Day {day_num}  ·  {day_name}'):^{W - 6}}  ║",
        f"╠{border}╣",
        f"║{' ' * (W - 2)}║",
    ]

    # Creature art (centered)
    for art_line in art:
        colored = color_fn(art_line)
        # Center based on visible (non-ANSI) width
        pad = max(0, (W - 2 - len(art_line)) // 2)
        lines.append(f"║{' ' * pad}{colored}{' ' * max(0, W - 2 - pad - len(art_line))}║")

    lines += [
        f"║{' ' * (W - 2)}║",
        f"║  {color_fn(bold(f'[ {mood_label} ]')):<{W + 6}}║",
        f"║  {dim(msg):<{W - 4}}║",
        f"║{' ' * (W - 2)}║",
        f"╠{'─' * (W - 2)}╣",
        f"║{' ' * (W - 2)}║",
        f"║  {'Hunger ':<9}{red(_hunger_bar(hunger_days)) if (hunger_days or 999) > 3 else green(_hunger_bar(hunger_days))}  {dim(_hunger_label(hunger_days)):<16}║",
        f"║  {'Applied':<9}{cyan(applied_b)}  {stats['total_applied']}/{stats['total']}{'  ✓' + str(stats['offers']) + ' offer' if stats['offers'] else ''}   ║",
        f"║  {'Streak ':<9}{yellow('🔥' * min(streak, 10)) if streak else dim('░░░░░░░░░░')}  {streak_str:<15}║",
    ]

    if stats["in_flight"] > 0:
        inflight_str = f"In flight: {stats['in_flight']}  ·  Overdue follow-ups: {stats['overdue']}"
        lines.append(f"║  {dim(inflight_str):<{W - 2}}║")
    if stats["overdue"] > 0:
        overdue_str = f"⚠  {stats['overdue']} follow-ups overdue!"
        lines.append(f"║  {red(bold(overdue_str))}{' ' * max(0, W - 30)}║")

    waiting_str = f"{stats['not_applied']} companies waiting  ·  run TUI to action them"
    lines += [
        f"║{' ' * (W - 2)}║",
        f"╠{'─' * (W - 2)}╣",
        f"║  {bold('Today: ')}{dim(today_goal):<{W - 10}}║",
        f"║  {dim(waiting_str):<{W - 4}}║",
        f"║{' ' * (W - 2)}║",
        f"╚{border}╝",
        f"  {dim('[t] open TUI  [q] quit  [enter] refresh')}",
    ]

    return "\n".join(lines)


# ── Interactive loop ──────────────────────────────────────────────────────────

def _getch_nonblock() -> Optional[str]:
    """Non-blocking single char read. Returns None if nothing ready."""
    import select
    import tty
    import termios
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if select.select([sys.stdin], [], [], 0.1)[0]:
            return sys.stdin.read(1)
        return None
    except Exception:
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def run_interactive(apps: list, tui_state: dict) -> None:
    hide_cursor()
    try:
        frame = 0
        try:
            W = min(os.get_terminal_size().columns, 62)
        except OSError:
            W = 62
        while True:
            stats = compute_stats(apps)
            output = render(stats, tui_state, frame=frame, terminal_width=W)
            print(clr() + output, end="", flush=True)
            frame += 1

            ch = _getch_nonblock()
            if ch in ("q", "Q", "\x03"):
                break
            if ch in ("t", "T", "\r", "\n"):
                show_cursor()
                print(clr(), end="")
                os.execlp("python3", "python3", str(BASE_DIR / "tracker.py"), "tui")

    finally:
        show_cursor()
        print()


def run_once(apps: list, tui_state: dict) -> None:
    stats = compute_stats(apps)
    try:
        W = min(os.get_terminal_size().columns, 62)
    except OSError:
        W = 62
    print(render(stats, tui_state, frame=0, terminal_width=W))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Appli — job search tamagotchi")
    parser.add_argument("--once", action="store_true", help="Print once and exit (no animation)")
    parser.add_argument("--reset", action="store_true", help="Reset state (first_run date)")
    args = parser.parse_args()

    tui_state = _load_state()
    if args.reset:
        tui_state["first_run"] = date.today().isoformat()
        _save_state(tui_state)
        print(f"Reset. Day 1 starts today ({date.today()}).")
        return

    apps = data_mod.load()

    if args.once:
        run_once(apps, tui_state)
    else:
        try:
            run_interactive(apps, tui_state)
        except KeyboardInterrupt:
            show_cursor()
            print()


if __name__ == "__main__":
    main()
