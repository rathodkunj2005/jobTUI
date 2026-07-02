#!/usr/bin/env python3
"""
tui.py — curses interactive TUI for the job search tracker.

Launch via:  python tracker.py tui
             python tui.py
"""
import curses
import subprocess
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
import data
import outreach as outreach_mod
import config as cfg_module
import job_fetcher
import resume_fit
import people_finder

# ── Color pair IDs ────────────────────────────────────────────────────────────
C_HEADER    = 1
C_SEL       = 2
C_TIER1     = 3
C_TIER2     = 4
C_TIER3     = 5
C_GREEN     = 6
C_YELLOW    = 7
C_RED       = 8
C_FOOTER    = 9
C_LABEL     = 10
C_FILTER    = 11
C_MODAL     = 12
C_MODAL_SEL = 13
C_OVERDUE   = 14
C_DIM_GREEN = 15
C_BAR_HIGH  = 16
C_BAR_MED   = 17
C_BAR_LOW   = 18
C_CONTEXT   = 19

STATUS_CP = {
    "Not Applied":       C_TIER3,
    "Watching":          C_TIER3,
    "Referral Pending":  C_YELLOW,
    "Applied":           C_GREEN,
    "Phone Screen":      C_GREEN,
    "Onsite":            C_GREEN,
    "Offer":             C_GREEN,
    "Rejected":          C_RED,
    "Withdrawn":         C_TIER3,
}

SORT_MODES = ["score", "tier", "company", "date_applied", "status"]
SORT_LABELS = {
    "score":        "Score↓",
    "tier":         "Tier+Score",
    "company":      "A-Z",
    "date_applied": "Applied↓",
    "status":       "Status",
}

_DEFAULT_FOLLOWUP_DAYS = 14


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_HEADER,    curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(C_SEL,       curses.COLOR_BLACK,   curses.COLOR_WHITE)
    curses.init_pair(C_TIER1,     curses.COLOR_CYAN,    -1)
    curses.init_pair(C_TIER2,     curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_TIER3,     -1,                   -1)
    curses.init_pair(C_GREEN,     curses.COLOR_GREEN,   -1)
    curses.init_pair(C_YELLOW,    curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_RED,       curses.COLOR_RED,     -1)
    curses.init_pair(C_FOOTER,    curses.COLOR_WHITE,   curses.COLOR_BLUE)
    curses.init_pair(C_LABEL,     curses.COLOR_CYAN,    -1)
    curses.init_pair(C_FILTER,    curses.COLOR_WHITE,   curses.COLOR_MAGENTA)
    curses.init_pair(C_MODAL,     curses.COLOR_WHITE,   curses.COLOR_BLACK)
    curses.init_pair(C_MODAL_SEL, curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(C_OVERDUE,   curses.COLOR_RED,     -1)
    curses.init_pair(C_DIM_GREEN, curses.COLOR_GREEN,   -1)
    curses.init_pair(C_BAR_HIGH,  curses.COLOR_GREEN,   -1)
    curses.init_pair(C_BAR_MED,   curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_BAR_LOW,   curses.COLOR_RED,     -1)
    curses.init_pair(C_CONTEXT,   curses.COLOR_WHITE,   -1)


# ── Score helpers ─────────────────────────────────────────────────────────────

_SCORE_MIN = 2.5
_SCORE_MAX = 5.0
_BAR_WIDTH  = 8


def _score_bar(score_float: float) -> str:
    """Return an 8-char block bar representing the score."""
    norm = max(0.0, min(1.0, (score_float - _SCORE_MIN) / (_SCORE_MAX - _SCORE_MIN)))
    filled = round(norm * _BAR_WIDTH)
    return "▓" * filled + "░" * (_BAR_WIDTH - filled)


def _score_bar_attr(score_float: float) -> int:
    if score_float >= 4.3:
        return curses.color_pair(C_BAR_HIGH) | curses.A_BOLD
    if score_float >= 3.5:
        return curses.color_pair(C_BAR_MED)
    return curses.color_pair(C_BAR_LOW) | curses.A_DIM


def _component_bar(val_str: str, max_val: int = 5) -> str:
    try:
        v = float(val_str)
    except (ValueError, TypeError):
        return "░" * max_val
    filled = round(v)
    return "▓" * filled + "░" * (max_val - filled)


def _days_ago(date_str: str) -> Optional[int]:
    try:
        d = date.fromisoformat(date_str)
        return (date.today() - d).days
    except (ValueError, AttributeError):
        return None


class JobTUI:
    def __init__(self, stdscr: "curses._CursesWindow") -> None:
        self.stdscr = stdscr
        self.apps: list[data.Application] = []
        self.visible: list[data.Application] = []
        self.cfg: dict = {}

        self.view = "list"
        self.cursor = 0
        self.list_scroll = 0
        self.content_scroll = 0

        self.selected: Optional[data.Application] = None

        # Filter / sort
        self.filter_str = ""
        self.filtering = False
        self.tier_filter: Optional[int] = None
        self.sort_mode = "score"

        # Overlays
        self.show_help = False

        # Inline note input
        self.note_input: Optional[str] = None
        self.noting = False

        # Inline followup-date input
        self.followup_input: Optional[str] = None
        self.following_up = False

        # Outreach state
        self.outreach_lines: list[str] = []
        self.outreach_subject = ""
        self.outreach_company = ""
        self.outreach_type = ""

        # Resume fit / people state
        self.fit_lines: list[str] = []
        self.fit_company = ""
        self.people_lines: list[str] = []
        self.people_company = ""
        self.people_searches: list[people_finder.PeopleSearch] = []

        self.status_msg = ""
        self._overdue_set: set[str] = set()

        # Job listings (fetched in background, cached)
        self.listings: dict[str, dict] = {}
        self._listings_loading = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def load(self) -> None:
        self.apps = data.load()
        try:
            self.cfg = cfg_module.load()
        except Exception:
            self.cfg = {}
        self._refresh_overdue()
        self._apply_filter()
        self._start_listings_fetch()

    def _start_listings_fetch(self) -> None:
        """Load cached listings immediately; refresh stale cache in background."""
        cached = job_fetcher.load_cache()
        if cached:
            self.listings = cached
        if job_fetcher.cache_is_stale():
            self._listings_loading = True
            if not self.listings:
                self.status_msg = "Fetching job listings…"
            else:
                self.status_msg = "Refreshing job listings in background…"
            t = threading.Thread(target=self._fetch_listings_bg, daemon=True)
            t.start()

    def _fetch_listings_bg(self) -> None:
        """Background thread: fetch all listings and update self.listings."""
        try:
            result = job_fetcher.fetch_all(
                self.apps,
                existing=self.listings,
                force=job_fetcher.cache_is_stale(),
            )
            job_fetcher.save_cache(result)
            self.listings = result
            total = sum(job_fetcher.listing_count(result, a.company) for a in self.apps)
            self.status_msg = f"Listings updated: {total} open roles across {len(result)} companies."
        except Exception as e:
            self.status_msg = f"Listings fetch error: {e}"
        finally:
            self._listings_loading = False

    def _refresh_overdue(self) -> None:
        self._overdue_set = {a.company for a in data.overdue_followups(self.apps)}

    def run(self) -> None:
        self.stdscr.keypad(True)
        curses.curs_set(0)
        curses.set_escdelay(50)
        _init_colors()
        self.load()

        while True:
            H, W = self.stdscr.getmaxyx()
            if H < 6 or W < 40:
                self.stdscr.erase()
                self._safe_addstr(0, 0, "Terminal too small — resize to at least 40×6.")
                self.stdscr.refresh()
                key = self.stdscr.getch()
                if key == ord("q"):
                    break
                continue

            try:
                self.draw()
            except curses.error:
                pass

            key = self.stdscr.getch()
            if not self._handle_key(key):
                break

    # ── Filter / sort ────────────────────────────────────────────────────────

    def _sorted(self, apps: list[data.Application]) -> list[data.Application]:
        m = self.sort_mode
        if m == "score":
            return sorted(apps, key=lambda a: (-a.score_float, a.tier_num))
        if m == "tier":
            return sorted(apps, key=lambda a: (a.tier_num, a.bucket, -a.score_float))
        if m == "company":
            return sorted(apps, key=lambda a: a.company.lower())
        if m == "date_applied":
            return sorted(apps, key=lambda a: a.date_applied or "0000-00-00", reverse=True)
        if m == "status":
            order = {s: i for i, s in enumerate(data.STATUSES)}
            return sorted(apps, key=lambda a: (order.get(a.status, 99), a.tier_num))
        return apps

    def _apply_filter(self) -> None:
        result = self.apps
        if self.tier_filter is not None:
            result = [a for a in result if a.tier_num == self.tier_filter]
        if self.filter_str:
            q = self.filter_str.lower()
            result = [
                a for a in result
                if q in a.company.lower()
                or q in a.role_family.lower()
                or q in a.status.lower()
                or q in a.tier.lower()
                or q in (a.notes or "").lower()
                or q in (a.contact_name or "").lower()
                or q in (a.strategy or "").lower()
            ]
        self.visible = self._sorted(result)
        self.cursor = min(self.cursor, max(0, len(self.visible) - 1))
        self._fix_list_scroll()

    def _fix_list_scroll(self) -> None:
        H, _ = self.stdscr.getmaxyx()
        rows = max(1, H - 6)
        if self.list_scroll > self.cursor:
            self.list_scroll = self.cursor
        if self.list_scroll + rows <= self.cursor:
            self.list_scroll = self.cursor - rows + 1
        self.list_scroll = max(0, self.list_scroll)

    # ── Attribute helpers ────────────────────────────────────────────────────

    def _tier_attr(self, app: data.Application) -> int:
        n = app.tier_num
        if n == 1:
            return curses.color_pair(C_TIER1) | curses.A_BOLD
        if n == 2:
            return curses.color_pair(C_TIER2)
        return curses.color_pair(C_TIER3) | curses.A_DIM

    def _tier_attr_n(self, n: int) -> int:
        if n == 1:
            return curses.color_pair(C_TIER1) | curses.A_BOLD
        if n == 2:
            return curses.color_pair(C_TIER2)
        return curses.color_pair(C_TIER3) | curses.A_DIM

    def _status_attr(self, status: str) -> int:
        cp = STATUS_CP.get(status, C_TIER3)
        attr = curses.color_pair(cp)
        if status == "Offer":
            attr |= curses.A_BOLD
        return attr

    # ── Safe draw helpers ────────────────────────────────────────────────────

    def _safe_addstr(self, y: int, x: int, s: str, attr: int = 0) -> None:
        H, W = self.stdscr.getmaxyx()
        if y < 0 or y >= H or x < 0 or x >= W:
            return
        s = s[: W - x]
        if not s:
            return
        try:
            self.stdscr.addstr(y, x, s, attr)
        except curses.error:
            pass

    def _fill_row(self, y: int, attr: int = 0) -> None:
        H, W = self.stdscr.getmaxyx()
        if y < 0 or y >= H:
            return
        try:
            self.stdscr.addstr(y, 0, " " * (W - 1), attr)
        except curses.error:
            pass

    # ── Draw orchestration ───────────────────────────────────────────────────

    def draw(self) -> None:
        self.stdscr.erase()
        H, W = self.stdscr.getmaxyx()

        self._draw_header(W)
        self._draw_tabs()

        content_top = 2
        content_h = H - 4

        if self.view == "list":
            self._draw_list(content_top, W, content_h)
        elif self.view == "detail":
            self._draw_detail(content_top, W, content_h)
        elif self.view == "outreach":
            self._draw_outreach(content_top, W, content_h)
        elif self.view == "next":
            self._draw_next(content_top, W, content_h)
        elif self.view == "stats":
            self._draw_stats(content_top, W, content_h)
        elif self.view == "fit":
            self._draw_plain_text(content_top, W, content_h, f"Resume Fit → {self.fit_company}", self.fit_lines)
        elif self.view == "people":
            self._draw_plain_text(content_top, W, content_h, f"People Search → {self.people_company}", self.people_lines)

        self._draw_footer(H, W)

        if self.filtering:
            self._draw_filter_bar(H, W)
        elif self.noting:
            self._draw_note_bar(H, W)
        elif self.following_up:
            self._draw_followup_bar(H, W)
        elif self.view == "list" and not self.status_msg:
            self._draw_context_strip(H, W)

        if self.show_help:
            self._draw_help_overlay(H, W)

        self.stdscr.refresh()

    # ── Header / tabs / footer ───────────────────────────────────────────────

    def _draw_header(self, W: int) -> None:
        count = len(self.visible)
        total = len(self.apps)
        applied = sum(1 for a in self.apps if a.status not in ("Not Applied", "Watching"))

        parts = []
        if self.tier_filter is not None:
            parts.append(f"T{self.tier_filter}")
        if self.filter_str:
            parts.append(f'"{self.filter_str}"')
        filter_tag = f"  [{', '.join(parts)}]" if parts else ""

        sort_tag = f"  /{SORT_LABELS[self.sort_mode]}"
        overdue_tag = f"  ⚠{len(self._overdue_set)}" if self._overdue_set else ""
        applied_tag = f"  ✓{applied}" if applied else ""
        listings_tag = "  ⟳listings" if self._listings_loading else ""

        title = f"  JOB TRACKER  ·  {count}/{total}{filter_tag}{sort_tag}{applied_tag}{overdue_tag}{listings_tag}"
        hint = " q:quit  ?:help  "
        pad = max(0, W - len(title) - len(hint))
        row = title + " " * pad + hint
        self._fill_row(0, curses.color_pair(C_HEADER) | curses.A_BOLD)
        self._safe_addstr(0, 0, row[:W - 1], curses.color_pair(C_HEADER) | curses.A_BOLD)

    def _draw_tabs(self) -> None:
        tabs = [("list", "LIST"), ("next", "NEXT"), ("stats", "STATS")]
        self._fill_row(1)
        x = 1
        active_base = self.view if self.view in ("list", "next", "stats") else "list"
        for view_id, label in tabs:
            attr = (curses.A_BOLD | curses.A_REVERSE) if view_id == active_base else curses.A_DIM
            s = f" {label} "
            self._safe_addstr(1, x, s, attr)
            x += len(s) + 1

        if self.view == "detail" and self.selected:
            tier_tag = f"T{self.selected.tier_num}{self.selected.bucket}"
            self._safe_addstr(1, x + 1, f"› {self.selected.company}  [{tier_tag}  {self.selected.score}]", curses.A_BOLD)
        elif self.view == "outreach" and self.outreach_company:
            self._safe_addstr(1, x + 1, f"› {self.outreach_company} / {self.outreach_type}", curses.A_BOLD)
        elif self.view == "fit" and self.fit_company:
            self._safe_addstr(1, x + 1, f"› Fit / {self.fit_company}", curses.A_BOLD)
        elif self.view == "people" and self.people_company:
            self._safe_addstr(1, x + 1, f"› People / {self.people_company}", curses.A_BOLD)

    def _draw_footer(self, H: int, W: int) -> None:
        self._fill_row(H - 2)
        self._fill_row(H - 1, curses.color_pair(C_FOOTER))

        if self.status_msg:
            self._safe_addstr(H - 2, 1, self.status_msg[:W - 2], curses.color_pair(C_YELLOW) | curses.A_BOLD)

        key_help = {
            "list":     "↑↓/jk  Enter:detail  I:resume-fit  P:people  A:apply  u:status  g:outreach  /:filter  Tab:sort",
            "detail":   "↑↓/jk  ]/[:prev/next  I:resume-fit  P:people  A:apply  R:tailor-resume  g:outreach  b/ESC:back",
            "outreach": "↑↓/jk  c:copy  b/ESC:back-to-detail  l:list",
            "fit":      "↑↓/jk  b/ESC:back-to-detail  l:list",
            "people":   "1-4:open LinkedIn search  ↑↓/jk  b/ESC:back-to-detail  l:list",
            "next":     "↑↓/jk  b/l:list  s:stats",
            "stats":    "↑↓/jk  b/l:list  n:next",
        }.get(self.view, "q:quit")
        self._safe_addstr(H - 1, 1, key_help[:W - 2], curses.color_pair(C_FOOTER))

    def _draw_context_strip(self, H: int, W: int) -> None:
        """Show hover info for selected company in the status row."""
        if not self.visible:
            return
        app = self.visible[self.cursor]
        days_found = _days_ago(app.date_found)
        age_str = f"  found {days_found}d ago" if days_found is not None else ""
        strategy_clip = app.strategy[:50] if app.strategy else "—"
        strip = f"  {app.role_family}  ·  {strategy_clip}{age_str}"
        self._safe_addstr(H - 2, 0, strip[:W - 1], curses.A_DIM)

    def _draw_filter_bar(self, H: int, W: int) -> None:
        tier_tag = f" T{self.tier_filter}" if self.tier_filter else ""
        prompt = f"  / Filter{tier_tag}: {self.filter_str}▌ "
        self._fill_row(H - 2, curses.color_pair(C_FILTER) | curses.A_BOLD)
        self._safe_addstr(H - 2, 0, prompt[:W - 1], curses.color_pair(C_FILTER) | curses.A_BOLD)

    def _draw_note_bar(self, H: int, W: int) -> None:
        app = self.selected or (self.visible[self.cursor] if self.visible else None)
        name = app.company[:20] if app else "?"
        text = self.note_input or ""
        prompt = f"  + Note [{name}]: {text}▌ "
        self._fill_row(H - 2, curses.color_pair(C_GREEN) | curses.A_BOLD)
        self._safe_addstr(H - 2, 0, prompt[:W - 1], curses.color_pair(C_GREEN) | curses.A_BOLD)

    def _draw_followup_bar(self, H: int, W: int) -> None:
        app = self.selected or (self.visible[self.cursor] if self.visible else None)
        name = app.company[:20] if app else "?"
        text = self.followup_input or ""
        prompt = f"  f Follow-up [{name}]: {text}▌  (YYYY-MM-DD, Enter to save, ESC cancel)"
        self._fill_row(H - 2, curses.color_pair(C_YELLOW) | curses.A_BOLD)
        self._safe_addstr(H - 2, 0, prompt[:W - 1], curses.color_pair(C_YELLOW) | curses.A_BOLD)

    # ── LIST view ────────────────────────────────────────────────────────────

    def _draw_list(self, top: int, W: int, content_h: int) -> None:
        # Dynamic column widths — bar eats 10 chars (space + 8 bar + space)
        bar_col_w = _BAR_WIDTH + 1   # bar + trailing space
        fixed = 1 + 4 + 2 + 6 + 1 + bar_col_w  # marker(1) num(4) gap(2) tier(6) gap(1)
        status_w = 18
        company_w = min(32, max(18, W - fixed - status_w - 4))
        url_w = max(0, min(35, W - fixed - status_w - company_w - 4)) if W >= 110 else 0

        # Column header
        hdr = f" {'#':>4}  {'Tier':<5} {'Score+Bar':<{_BAR_WIDTH + 6}}  {'Company':<{company_w}} {'Status':<{status_w}}"
        if url_w:
            hdr += " URL"
        sort_ind = f" {SORT_LABELS[self.sort_mode]} "
        self._safe_addstr(top, 0, hdr, curses.A_BOLD)
        self._safe_addstr(top, W - len(sort_ind) - 1, sort_ind, curses.A_DIM | curses.A_REVERSE)
        self._safe_addstr(top + 1, 0, "─" * (W - 1), curses.A_DIM)

        if not self.visible:
            self._safe_addstr(top + 3, 4, "No companies match the filter.", curses.A_DIM)
            return

        row_area = content_h - 2
        for rel, i in enumerate(range(self.list_scroll, min(self.list_scroll + row_area, len(self.visible)))):
            app = self.visible[i]
            y = top + 2 + rel
            is_sel = (i == self.cursor)
            is_overdue = app.company in self._overdue_set
            has_listings = job_fetcher.listing_count(self.listings, app.company) > 0
            tier_label = f"T{app.tier_num}{app.bucket}"
            marker = "!" if is_overdue else ("★" if has_listings else " ")
            bar = _score_bar(app.score_float)

            if is_sel:
                self._fill_row(y, curses.color_pair(C_SEL) | curses.A_BOLD)
                row = (
                    f"{marker}{i+1:>4}  {tier_label:<5} {app.score:>5} {bar}  "
                    f"{app.company:<{company_w}} {app.status:<{status_w}}"
                )
                if url_w and app.job_url:
                    u = app.job_url[:url_w - 1] + "…" if len(app.job_url) > url_w else app.job_url
                    row += f" {u}"
                self._safe_addstr(y, 0, row, curses.color_pair(C_SEL) | curses.A_BOLD)
            else:
                # marker
                m_attr = (curses.color_pair(C_OVERDUE) | curses.A_BOLD) if is_overdue else curses.A_DIM
                self._safe_addstr(y, 0, marker, m_attr)
                # index
                self._safe_addstr(y, 1, f"{i+1:>4}  ", curses.A_DIM)
                # tier
                self._safe_addstr(y, 7, f"{tier_label:<5}", self._tier_attr(app))
                # score number
                self._safe_addstr(y, 13, f" {app.score:>5} ", curses.A_BOLD)
                # score bar
                self._safe_addstr(y, 20, bar, _score_bar_attr(app.score_float))
                # company
                self._safe_addstr(y, 20 + _BAR_WIDTH + 2, f"{app.company:<{company_w}} ", 0)
                x_status = 20 + _BAR_WIDTH + 2 + company_w + 1
                self._safe_addstr(y, x_status, f"{app.status:<{status_w}}", self._status_attr(app.status))
                if url_w and app.job_url:
                    x_url = x_status + status_w + 1
                    u = app.job_url[:url_w - 1] + "…" if len(app.job_url) > url_w else app.job_url
                    self._safe_addstr(y, x_url, u, curses.A_DIM)

        # Scroll indicator (top-right of content)
        end = min(self.list_scroll + row_area, len(self.visible))
        ind = f" {self.list_scroll + 1}–{end}/{len(self.visible)} "
        self._safe_addstr(top + 1, max(0, W - len(ind) - 1), ind, curses.A_DIM)

    # ── DETAIL view ──────────────────────────────────────────────────────────

    def _draw_detail(self, top: int, W: int, content_h: int) -> None:
        app = self.selected
        if not app:
            return

        label_w = 22
        sep = "─" * min(62, W - 2)
        is_overdue = app.company in self._overdue_set

        # Find position in visible list for nav hint
        try:
            pos_idx = next(i for i, a in enumerate(self.visible) if a.company == app.company)
            nav_hint = f"  {pos_idx + 1}/{len(self.visible)}  [/]:prev/next"
        except StopIteration:
            nav_hint = ""

        overdue_str = "  ⚠ FOLLOW-UP OVERDUE" if is_overdue else ""

        # Score component bars
        score_lines: list[tuple] = [
            ("score_row", "SWE Fit",   app.swe_fit),
            ("score_row", "AI/ML Fit", app.aiml_fit),
            ("score_row", "Referral",  app.referral_likelihood),
            ("score_row", "Comp",      app.comp_upside),
            ("score_row", "Realism",   app.realism),
            ("score_total", app.score),
        ]

        # Time info
        days_found = _days_ago(app.date_found)
        days_applied = _days_ago(app.date_applied)
        timing_str = ""
        if days_found is not None:
            timing_str += f"found {days_found}d ago"
        if days_applied is not None:
            timing_str += f"  ·  applied {days_applied}d ago"

        lines: list[tuple] = [
            ("title",   app.company + overdue_str),
            ("nav",     nav_hint),
            ("sep",     sep),
            ("field",   "Tier / Bucket / Rank",  f"{app.tier}  ·  bucket {app.bucket}  ·  rank {app.rank}"),
            ("field",   "Role Family",            app.role_family),
            ("field",   "Focus",                  app.focus),
            ("field",   "Resume Variant",         app.resume),
            ("field",   "Strategy",               app.strategy),
            ("sep",     sep),
            ("field",   "Status",                 app.status),
        ]
        lines += score_lines
        lines += [
            ("sep",     sep),
            ("field",   "Contact",                app.contact_name or "—"),
            ("field",   "Date Found",             app.date_found or "—"),
            ("field",   "Date Applied",           app.date_applied or "—"),
            ("field",   "Follow-up Date",         app.followup_date or "—"),
        ]
        if timing_str:
            lines.append(("timing", timing_str))
        lines.append(("field", "Job URL", app.job_url or "—"))

        # Live job listings
        job_listings = job_fetcher.listing_titles(self.listings, app.company)
        n_listings = len(job_listings)
        ats = (self.listings.get(app.company) or {}).get("ats") or ""
        if self._listings_loading and not job_listings:
            lines += [("sep", sep), ("listing_status", "⟳ Fetching open roles…")]
        elif job_listings:
            ats_tag = f" via {ats}" if ats else ""
            lines += [("sep", sep), ("listing_hdr", f"Open Roles ({n_listings}{ats_tag})")]
            for job in job_listings[:12]:
                loc = job.get("location", "")
                loc_str = f"  [{loc}]" if loc else ""
                lines.append(("listing", job["title"], loc_str))
            if n_listings > 12:
                lines.append(("listing_more", f"… and {n_listings - 12} more — e:open careers page"))
        elif not self._listings_loading:
            lines += [("sep", sep), ("listing_status", "No targeted roles found via public API")]

        if app.notes:
            lines += [("sep", sep), ("notes", app.notes)]
        lines += [
            ("sep",  sep),
            ("hint", "I:resume-fit  P:people  A:apply-today  u:status  f:followup  a:note  g:outreach  e:URL  ]/[:next/prev  b/ESC:back"),
        ]

        for rel, item in enumerate(lines[self.content_scroll: self.content_scroll + content_h]):
            y = top + rel
            kind = item[0]
            if kind == "title":
                attr = (curses.color_pair(C_RED) | curses.A_BOLD) if is_overdue else (curses.color_pair(C_TIER1) | curses.A_BOLD)
                self._safe_addstr(y, 2, item[1], attr)
            elif kind == "nav":
                self._safe_addstr(y, 2, item[1], curses.A_DIM)
            elif kind == "sep":
                self._safe_addstr(y, 1, item[1], curses.A_DIM)
            elif kind == "hint":
                self._safe_addstr(y, 2, item[1], curses.A_DIM)
            elif kind == "notes":
                prefix = "  Notes: "
                self._safe_addstr(y, 0, prefix, curses.color_pair(C_LABEL))
                self._safe_addstr(y, len(prefix), item[1][:W - len(prefix) - 1], curses.color_pair(C_YELLOW))
            elif kind == "timing":
                self._safe_addstr(y, 26, item[1], curses.A_DIM)
            elif kind == "score_row":
                _, label, val_str = item
                lstr = f"  {'  ' + label:<{label_w}}: "
                self._safe_addstr(y, 0, lstr, curses.color_pair(C_LABEL))
                xv = len(lstr)
                bar = _component_bar(val_str)
                try:
                    v = float(val_str)
                    bar_attr = _score_bar_attr(v * 0.85)  # scale 1-5 → ~0-4.25 range
                except (ValueError, TypeError):
                    bar_attr = curses.A_DIM
                self._safe_addstr(y, xv, bar, bar_attr)
                self._safe_addstr(y, xv + 6, f"  {val_str}/5", 0)
            elif kind == "score_total":
                score_str = item[1]
                lstr = f"  {'  ═► Score':<{label_w}}: "
                self._safe_addstr(y, 0, lstr, curses.color_pair(C_LABEL))
                xv = len(lstr)
                try:
                    sf = float(score_str)
                    attr = _score_bar_attr(sf)
                except (ValueError, TypeError):
                    attr = curses.A_BOLD
                self._safe_addstr(y, xv, f"{score_str}  {_score_bar(float(score_str) if score_str else 0)}", attr | curses.A_BOLD)
            elif kind == "listing_hdr":
                self._safe_addstr(y, 2, item[1], curses.color_pair(C_GREEN) | curses.A_BOLD)
            elif kind == "listing_status":
                self._safe_addstr(y, 2, item[1], curses.A_DIM)
            elif kind == "listing":
                _, title, loc_str = item
                full = f"  • {title}{loc_str}"
                self._safe_addstr(y, 0, full[:W - 1], curses.color_pair(C_TIER2))
            elif kind == "listing_more":
                self._safe_addstr(y, 2, item[1], curses.A_DIM)
            elif kind == "field":
                _, label, value = item
                lstr = f"  {label:<{label_w}}: "
                self._safe_addstr(y, 0, lstr, curses.color_pair(C_LABEL))
                xv = len(lstr)
                if label == "Status":
                    self._safe_addstr(y, xv, value, self._status_attr(value) | curses.A_BOLD)
                elif label == "Job URL" and value != "—":
                    self._safe_addstr(y, xv, value[:W - xv - 1], curses.A_UNDERLINE)
                elif label == "Follow-up Date" and is_overdue and value != "—":
                    self._safe_addstr(y, xv, value + "  ⚠ overdue", curses.color_pair(C_RED) | curses.A_BOLD)
                else:
                    self._safe_addstr(y, xv, value[:W - xv - 1], 0)

    # ── OUTREACH view ────────────────────────────────────────────────────────

    def _draw_outreach(self, top: int, W: int, content_h: int) -> None:
        hdr = f"  Outreach: {self.outreach_type.upper()}  →  {self.outreach_company}"
        self._safe_addstr(top, 0, hdr, curses.color_pair(C_GREEN) | curses.A_BOLD)
        self._safe_addstr(top + 1, 0, "─" * (W - 1), curses.A_DIM)

        avail = content_h - 2
        total = len(self.outreach_lines)
        for rel, line in enumerate(self.outreach_lines[self.content_scroll: self.content_scroll + avail]):
            y = top + 2 + rel
            if line.startswith("Subject:"):
                self._safe_addstr(y, 0, line[:W - 1], curses.A_BOLD)
            elif line.startswith("─") or line.startswith("━"):
                self._safe_addstr(y, 0, line[:W - 1], curses.A_DIM)
            else:
                self._safe_addstr(y, 0, line[:W - 1], 0)

        end = min(self.content_scroll + avail, total)
        ind = f" {self.content_scroll + 1}–{end}/{total}  c:copy "
        self._safe_addstr(top + 1, max(0, W - len(ind) - 1), ind, curses.A_DIM)

    # ── Plain text views (fit / people) ───────────────────────────────────────
    def _draw_plain_text(self, top: int, W: int, content_h: int, title: str, lines: list[str]) -> None:
        self._safe_addstr(top, 0, f"  {title}", curses.color_pair(C_GREEN) | curses.A_BOLD)
        self._safe_addstr(top + 1, 0, "─" * (W - 1), curses.A_DIM)
        avail = content_h - 2
        total = len(lines)
        for rel, line in enumerate(lines[self.content_scroll: self.content_scroll + avail]):
            y = top + 2 + rel
            attr = 0
            if line.startswith("#") or line.startswith("##"):
                attr = curses.A_BOLD
            elif line.startswith("- Missing") or "risk" in line.lower():
                attr = curses.color_pair(C_YELLOW)
            elif line.startswith("http") or "linkedin.com" in line:
                attr = curses.A_UNDERLINE | curses.color_pair(C_TIER1)
            self._safe_addstr(y, 0, line[:W - 1], attr)
        end = min(self.content_scroll + avail, total)
        ind = f" {self.content_scroll + 1}–{end}/{total} " if total else " 0/0 "
        self._safe_addstr(top + 1, max(0, W - len(ind) - 1), ind, curses.A_DIM)

    # ── NEXT view ────────────────────────────────────────────────────────────

    def _draw_next(self, top: int, W: int, content_h: int) -> None:
        next_apps = data.next_actions(self.apps, limit=20)
        overdue = data.overdue_followups(self.apps)

        lines: list[tuple] = []
        if overdue:
            lines.append(("warn", f"⚠  OVERDUE FOLLOW-UPS ({len(overdue)})"))
            for a in overdue:
                lines.append(("text", f"  {a.company:<34}  follow-up: {a.followup_date}  [{a.status}]"))
            lines.append(("sep", "─" * min(70, W - 2)))

        lines.append(("bold", f"Top {len(next_apps)} actionable companies (tier + score)"))
        lines.append(("sep",  "─" * min(70, W - 2)))
        lines.append(("head", f"{'#':>3}  {'Tier':<8}{'Score':<14}  {'Company':<28}  {'Role':<22}  Variant"))

        for i, app in enumerate(next_apps, 1):
            lines.append(("app", i, app))

        today = date.today()
        day_name = today.strftime("%A")
        cadence = {
            "Monday":    "Review Tier 1 openings, pick 3 priority roles, customize resume.",
            "Tuesday":   "Submit 2 Tier 1 apps + 5 referral/outreach messages.",
            "Wednesday": "Submit 1 Tier 1 + 2 Tier 2 apps. Log responses.",
            "Thursday":  "Submit 3 Tier 2 apps + 5 more outreach messages.",
            "Friday":    "Submit 2 Tier 3 or opportunistic apps. Follow up on prior outreach.",
            "Saturday":  "90-min prep: DS&A + systems + AI/ML fundamentals.",
            "Sunday":    "Refresh tracker, review funnel metrics, prep next week.",
        }
        lines += [
            ("sep",  ""),
            ("text", f"Today: {day_name}, {today}"),
            ("text", f"→ {cadence.get(day_name, 'Review tracker.')}"),
        ]

        for rel, item in enumerate(lines[self.content_scroll: self.content_scroll + content_h]):
            y = top + rel
            kind = item[0]
            if kind == "bold":
                self._safe_addstr(y, 0, item[1], curses.A_BOLD)
            elif kind == "warn":
                self._safe_addstr(y, 0, item[1], curses.color_pair(C_RED) | curses.A_BOLD)
            elif kind == "sep":
                self._safe_addstr(y, 0, item[1], curses.A_DIM)
            elif kind == "head":
                self._safe_addstr(y, 0, item[1][:W - 1], curses.A_BOLD)
            elif kind == "text":
                self._safe_addstr(y, 0, item[1][:W - 1], curses.A_DIM)
            elif kind == "app":
                _, idx, app = item
                tl = f"T{app.tier_num}{app.bucket}"
                ov = "!" if app.company in self._overdue_set else " "
                bar = _score_bar(app.score_float)
                row = f"{ov}{idx:>2}  {tl:<8}{app.score:<5} {bar}  {app.company:<28}  {app.role_family[:22]:<22}  {app.resume}"
                attr = _score_bar_attr(app.score_float) if app.company not in self._overdue_set else (curses.color_pair(C_OVERDUE) | curses.A_BOLD)
                self._safe_addstr(y, 0, row[:W - 1], attr)

    # ── STATS view ───────────────────────────────────────────────────────────

    def _draw_stats(self, top: int, W: int, content_h: int) -> None:
        apps = self.apps
        total = len(apps)
        by_status: dict[str, int] = {}
        by_tier: dict[int, int] = {}
        by_role: dict[str, int] = {}
        acted = 0

        for app in apps:
            by_status[app.status] = by_status.get(app.status, 0) + 1
            by_tier[app.tier_num] = by_tier.get(app.tier_num, 0) + 1
            by_role[app.role_family] = by_role.get(app.role_family, 0) + 1
            if app.status not in ("Not Applied", "Watching"):
                acted += 1

        bar_w = min(20, max(5, W - 38))
        pct = 100 * acted // total if total else 0

        applied_n  = sum(by_status.get(s, 0) for s in ("Applied", "Phone Screen", "Onsite", "Offer", "Rejected", "Withdrawn"))
        screened_n = sum(by_status.get(s, 0) for s in ("Phone Screen", "Onsite", "Offer"))
        onsite_n   = sum(by_status.get(s, 0) for s in ("Onsite", "Offer"))
        offer_n    = by_status.get("Offer", 0)

        def conv(num: int, denom: int) -> str:
            return f"{100*num//denom}%" if denom else "—"

        lines: list[tuple] = [
            ("bold", "═══  Application Funnel  ═══"),
            ("text", f"  Total tracked     : {total}"),
            ("text", f"  Action taken      : {acted}  ({pct}%)"),
            ("sep",  ""),
            ("bold", "  Conversion:"),
            ("text", f"    Applied  {applied_n:>3}  →  Screen {screened_n:>3} ({conv(screened_n, applied_n)})  →  Onsite {onsite_n:>3} ({conv(onsite_n, screened_n)})  →  Offer {offer_n:>3}"),
            ("sep",  ""),
            ("bold", "  By Status:"),
        ]
        for status in data.STATUSES:
            count = by_status.get(status, 0)
            filled = int(bar_w * count / total) if total else 0
            bar = "█" * filled + "░" * (bar_w - filled)
            lines.append(("status", status, count, bar))

        lines += [("sep", ""), ("bold", "  By Tier:")]
        for tn in sorted(by_tier):
            count = by_tier[tn]
            done = sum(1 for a in apps if a.tier_num == tn and a.status not in ("Not Applied", "Watching"))
            avg_score = sum(a.score_float for a in apps if a.tier_num == tn) / count if count else 0
            pct_t = 100 * done // count if count else 0
            lines.append(("tier", tn, count, done, pct_t, avg_score))

        lines += [("sep", ""), ("bold", "  By Role Family (top 10):")]
        top_roles = sorted(by_role.items(), key=lambda x: -x[1])[:10]
        for role, cnt in top_roles:
            role_bar_w = min(15, max(1, round(bar_w * cnt / total))) if total else 0
            lines.append(("role", role, cnt, "█" * role_bar_w))

        for rel, item in enumerate(lines[self.content_scroll: self.content_scroll + content_h]):
            y = top + rel
            kind = item[0]
            if kind == "bold":
                self._safe_addstr(y, 0, item[1], curses.A_BOLD)
            elif kind in ("text", "sep"):
                self._safe_addstr(y, 0, item[1], 0)
            elif kind == "status":
                _, st, cnt, bar = item
                s = f"    {st:<20} {cnt:>3}  {bar}"
                self._safe_addstr(y, 0, s[:W - 1], self._status_attr(st))
            elif kind == "tier":
                _, tn, cnt, done, pct_t, avg = item
                s = f"    Tier {tn}  {cnt:>3} companies  {done:>3} acted ({pct_t}%)  avg score {avg:.2f}"
                self._safe_addstr(y, 0, s[:W - 1], self._tier_attr_n(tn))
            elif kind == "role":
                _, role, cnt, bar = item
                s = f"    {role:<28} {cnt:>3}  {bar}"
                self._safe_addstr(y, 0, s[:W - 1], curses.A_DIM)

    # ── HELP overlay ─────────────────────────────────────────────────────────

    def _draw_help_overlay(self, H: int, W: int) -> None:
        lines = [
            "  KEY REFERENCE",
            "  ─────────────────────────────────────────",
            "  Navigation",
            "    ↑↓ / j k         move / scroll",
            "    PgUp / PgDn      page up / down",
            "    Home / End       first / last row",
            "    Enter            open detail view",
            "    ] / [            next / prev company (detail)",
            "    b / ESC          back / clear filter",
            "  ",
            "  Views",
            "    n                NEXT actions",
            "    s                STATS funnel",
            "    l                LIST (from any view)",
            "  ",
            "  Actions (list or detail)",
            "    A                mark Applied Today + set followup",
            "    u                update status (modal)",
            "    f                set follow-up date",
            "    a                append note",
            "    e                open Job URL in browser",
            "    g                generate outreach message",
            "    I                assess latest/current resume vs job",
            "    P                show LinkedIn people-search links",
            "    R                generate personalized resume PDF",
            "    r                reload data from CSV",
            "  ",
            "  Outreach (type picker)",
            "    r  referral  ·  e  recruiter",
            "    a  alumni   ·  l  linkedIn",
            "    c  copy to clipboard",
            "  ",
            "  Filtering & Sorting",
            "    /                text filter",
            "    1 / 2 / 3        tier filter toggle",
            "    0 / ESC          clear all filters",
            "    Tab              cycle sort mode",
            "  ",
            "  ?                  toggle this help",
            "  q                  quit",
            "  ─────────────────────────────────────────",
            "  Press any key to close",
        ]

        box_h = len(lines) + 2
        box_w = min(W - 4, 50)
        y0 = max(0, (H - box_h) // 2)
        x0 = max(0, (W - box_w) // 2)

        attr = curses.color_pair(C_MODAL) | curses.A_BOLD
        for dy in range(box_h):
            y = y0 + dy
            if y >= H:
                break
            self._fill_row(y, attr)
            if 0 < dy <= len(lines):
                self._safe_addstr(y, x0, lines[dy - 1][:box_w - 1], attr)

    # ── STATUS UPDATE modal ──────────────────────────────────────────────────

    def _status_modal(self, app: data.Application) -> None:
        statuses = data.STATUSES
        try:
            cur_idx = statuses.index(app.status)
        except ValueError:
            cur_idx = 0

        while True:
            H, W = self.stdscr.getmaxyx()
            box_h = len(statuses) + 4
            box_w = min(W - 4, 40)
            y0 = max(1, (H - box_h) // 2)
            x0 = max(0, (W - box_w) // 2)
            modal_attr = curses.color_pair(C_MODAL) | curses.A_BOLD

            for dy in range(box_h):
                y = y0 + dy
                if y >= H:
                    break
                self._fill_row(y, modal_attr)

            title = f" Status: {app.company[:22]} "
            self._safe_addstr(y0, x0 + 2, title, modal_attr)
            self._safe_addstr(y0 + 1, x0 + 2, "─" * (box_w - 4), modal_attr)

            for i, s in enumerate(statuses):
                y = y0 + 2 + i
                if y >= H:
                    break
                if i == cur_idx:
                    self._safe_addstr(y, x0 + 2, f"  ▶ {s:<22}  ", curses.color_pair(C_MODAL_SEL) | curses.A_BOLD)
                else:
                    self._safe_addstr(y, x0 + 2, f"    {s:<22}  ", modal_attr)

            self._safe_addstr(y0 + 2 + len(statuses), x0 + 2, "  Enter:select  ESC:cancel", modal_attr)
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                cur_idx = max(0, cur_idx - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                cur_idx = min(len(statuses) - 1, cur_idx + 1)
            elif key in (10, 13, curses.KEY_ENTER):
                new_status = statuses[cur_idx]
                if new_status != app.status:
                    app.status = new_status
                    data.save(self.apps)
                    self._refresh_overdue()
                    self.status_msg = f"Status → {new_status}"
                else:
                    self.status_msg = "Status unchanged."
                return
            elif key == 27:
                self.status_msg = "Cancelled."
                return

    # ── Apply Today ──────────────────────────────────────────────────────────

    def _apply_today(self, app: data.Application) -> None:
        today_str = date.today().isoformat()
        app.status = "Applied"
        app.date_applied = today_str
        if not app.followup_date:
            app.followup_date = (date.today() + timedelta(days=_DEFAULT_FOLLOWUP_DAYS)).isoformat()
        data.save(self.apps)
        self._refresh_overdue()
        self._apply_filter()
        self.status_msg = f"✓ Applied {app.company} on {today_str}. Follow-up: {app.followup_date}"

    # ── Followup date input ──────────────────────────────────────────────────

    def _start_followup(self, app: data.Application) -> None:
        self.selected = app
        default = app.followup_date or (date.today() + timedelta(days=_DEFAULT_FOLLOWUP_DAYS)).isoformat()
        self.followup_input = default
        self.following_up = True
        self.status_msg = ""

    def _handle_followup_key(self, key: int) -> bool:
        if key == 27:
            self.following_up = False
            self.followup_input = None
            self.status_msg = "Cancelled."
        elif key in (10, 13, curses.KEY_ENTER):
            text = (self.followup_input or "").strip()
            try:
                date.fromisoformat(text)
            except ValueError:
                self.status_msg = f"Invalid date: '{text}'. Use YYYY-MM-DD."
                self.following_up = False
                self.followup_input = None
                return True
            if self.selected:
                self.selected.followup_date = text
                data.save(self.apps)
                self._refresh_overdue()
                self.status_msg = f"Follow-up set: {text}"
            self.following_up = False
            self.followup_input = None
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if self.followup_input:
                self.followup_input = self.followup_input[:-1]
        elif 32 <= key <= 126:
            self.followup_input = (self.followup_input or "") + chr(key)
        return True

    # ── Note append ──────────────────────────────────────────────────────────

    def _start_note(self, app: data.Application) -> None:
        self.selected = app
        self.note_input = ""
        self.noting = True
        self.status_msg = ""

    def _handle_note_key(self, key: int) -> bool:
        if key == 27:
            self.noting = False
            self.note_input = None
            self.status_msg = "Cancelled."
        elif key in (10, 13, curses.KEY_ENTER):
            if self.note_input and self.selected:
                sep = " | " if self.selected.notes else ""
                self.selected.notes = self.selected.notes + sep + self.note_input
                data.save(self.apps)
                self.status_msg = "Note saved."
            self.noting = False
            self.note_input = None
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if self.note_input:
                self.note_input = self.note_input[:-1]
        elif 32 <= key <= 126:
            self.note_input = (self.note_input or "") + chr(key)
        return True

    # ── Detail navigation ────────────────────────────────────────────────────

    def _nav_detail(self, direction: int) -> None:
        if not self.visible or not self.selected:
            return
        try:
            idx = next(i for i, a in enumerate(self.visible) if a.company == self.selected.company)
        except StopIteration:
            return
        new_idx = max(0, min(len(self.visible) - 1, idx + direction))
        if new_idx != idx:
            self.cursor = new_idx
            self.selected = self.visible[new_idx]
            self.content_scroll = 0
            self._fix_list_scroll()
            self.status_msg = ""

    # ── Key handling ─────────────────────────────────────────────────────────

    def _handle_key(self, key: int) -> bool:
        if key == curses.KEY_RESIZE:
            self.stdscr.clear()
            self._fix_list_scroll()
            return True

        if self.show_help:
            self.show_help = False
            return True

        if self.following_up:
            return self._handle_followup_key(key)

        if self.noting:
            return self._handle_note_key(key)

        if self.filtering:
            return self._handle_filter_key(key)

        if key == ord("q"):
            return False
        if key == ord("?"):
            self.show_help = True
            return True

        if self.view == "list":
            return self._key_list(key)
        if self.view == "detail":
            return self._key_detail(key)
        if self.view == "outreach":
            return self._key_outreach(key)
        if self.view == "people":
            return self._key_people(key)
        if self.view in ("next", "stats", "fit"):
            return self._key_scroll(key)
        return True

    def _handle_filter_key(self, key: int) -> bool:
        if key == 27:
            self.filter_str = ""
            self.filtering = False
            self._apply_filter()
        elif key in (10, 13, curses.KEY_ENTER):
            self.filtering = False
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            self.filter_str = self.filter_str[:-1]
            self._apply_filter()
        elif 32 <= key <= 126:
            self.filter_str += chr(key)
            self._apply_filter()
        return True

    def _key_list(self, key: int) -> bool:
        H, _ = self.stdscr.getmaxyx()
        rows = max(1, H - 6)

        if key in (curses.KEY_UP, ord("k")):
            self.cursor = max(0, self.cursor - 1)
            self._fix_list_scroll()
            self.status_msg = ""
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor = min(len(self.visible) - 1, self.cursor + 1)
            self._fix_list_scroll()
            self.status_msg = ""
        elif key == curses.KEY_PPAGE:
            self.cursor = max(0, self.cursor - rows)
            self._fix_list_scroll()
        elif key == curses.KEY_NPAGE:
            self.cursor = min(len(self.visible) - 1, self.cursor + rows)
            self._fix_list_scroll()
        elif key == curses.KEY_HOME:
            self.cursor = 0
            self.list_scroll = 0
        elif key == curses.KEY_END:
            self.cursor = max(0, len(self.visible) - 1)
            self._fix_list_scroll()
        elif key in (10, 13, curses.KEY_ENTER):
            if self.visible:
                self.selected = self.visible[self.cursor]
                self.content_scroll = 0
                self.view = "detail"
                self.status_msg = ""
        elif key == ord("A"):
            if self.visible:
                self._apply_today(self.visible[self.cursor])
        elif key == ord("g"):
            if self.visible:
                self.selected = self.visible[self.cursor]
                self._start_generate()
        elif key == ord("I"):
            if self.visible:
                self.selected = self.visible[self.cursor]
                self._start_fit_assessment()
        elif key == ord("P"):
            if self.visible:
                self.selected = self.visible[self.cursor]
                self._show_people_searches()
        elif key == ord("u"):
            if self.visible:
                app = self.visible[self.cursor]
                self._status_modal(app)
                self._apply_filter()
        elif key == ord("f"):
            if self.visible:
                self._start_followup(self.visible[self.cursor])
        elif key == ord("a"):
            if self.visible:
                self._start_note(self.visible[self.cursor])
        elif key == ord("e"):
            if self.visible:
                self.selected = self.visible[self.cursor]
                self._open_url()
        elif key == ord("/"):
            self.filtering = True
            self.status_msg = ""
        elif key == 27:
            if self.filter_str or self.tier_filter is not None:
                self.filter_str = ""
                self.tier_filter = None
                self._apply_filter()
                self.status_msg = "Filters cleared."
        elif key == ord("0"):
            self.tier_filter = None
            self._apply_filter()
            self.status_msg = "Tier filter cleared."
        elif key in (ord("1"), ord("2"), ord("3")):
            t = int(chr(key))
            self.tier_filter = t if self.tier_filter != t else None
            self._apply_filter()
            self.cursor = 0
            self.list_scroll = 0
            self.status_msg = f"Tier {t} filter {'on' if self.tier_filter else 'off'}."
        elif key == ord("\t"):
            idx = SORT_MODES.index(self.sort_mode)
            self.sort_mode = SORT_MODES[(idx + 1) % len(SORT_MODES)]
            self._apply_filter()
            self.status_msg = f"Sort: {SORT_LABELS[self.sort_mode]}"
        elif key == ord("n"):
            self.view = "next"
            self.content_scroll = 0
        elif key == ord("s"):
            self.view = "stats"
            self.content_scroll = 0
        elif key == ord("r"):
            self.load()
            self.status_msg = "Reloaded."
        return True

    def _key_detail(self, key: int) -> bool:
        H, _ = self.stdscr.getmaxyx()
        rows = max(1, H - 6)

        if key in (curses.KEY_UP, ord("k")):
            self.content_scroll = max(0, self.content_scroll - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.content_scroll += 1
        elif key == curses.KEY_PPAGE:
            self.content_scroll = max(0, self.content_scroll - rows)
        elif key == curses.KEY_NPAGE:
            self.content_scroll += rows
        elif key == ord("]"):
            self._nav_detail(+1)
        elif key == ord("["):
            self._nav_detail(-1)
        elif key in (27, ord("b"), ord("l")):
            self.view = "list"
            self.content_scroll = 0
        elif key == ord("A"):
            if self.selected:
                self._apply_today(self.selected)
        elif key == ord("g"):
            self._start_generate()
        elif key == ord("I"):
            self._start_fit_assessment()
        elif key == ord("P"):
            self._show_people_searches()
        elif key == ord("u"):
            if self.selected:
                self._status_modal(self.selected)
        elif key == ord("f"):
            if self.selected:
                self._start_followup(self.selected)
        elif key == ord("a"):
            if self.selected:
                self._start_note(self.selected)
        elif key == ord("e"):
            self._open_url()
        elif key == ord("r"):
            self.load()
            if self.selected:
                self.selected = data.find(self.apps, self.selected.company)
            self.status_msg = "Reloaded."
        elif key == ord("R"):
            self._start_resume_gen()
        return True

    def _key_outreach(self, key: int) -> bool:
        if key in (curses.KEY_UP, ord("k")):
            self.content_scroll = max(0, self.content_scroll - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.content_scroll += 1
        elif key in (27, ord("b")):
            self.view = "detail"
            self.content_scroll = 0
        elif key == ord("l"):
            self.view = "list"
            self.content_scroll = 0
        elif key == ord("c"):
            self._copy_outreach()
        return True

    def _key_people(self, key: int) -> bool:
        if key in (ord("1"), ord("2"), ord("3"), ord("4")):
            idx = int(chr(key)) - 1
            if 0 <= idx < len(self.people_searches):
                subprocess.run(["open", self.people_searches[idx].url], check=False, capture_output=True)
                self.status_msg = f"Opened LinkedIn search: {self.people_searches[idx].label}"
        elif key in (27, ord("b")):
            self.view = "detail"
            self.content_scroll = 0
        elif key == ord("l"):
            self.view = "list"
            self.content_scroll = 0
        else:
            return self._key_scroll(key)
        return True

    def _key_scroll(self, key: int) -> bool:
        H, _ = self.stdscr.getmaxyx()
        rows = max(1, H - 6)

        if key in (curses.KEY_UP, ord("k")):
            self.content_scroll = max(0, self.content_scroll - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.content_scroll += 1
        elif key == curses.KEY_PPAGE:
            self.content_scroll = max(0, self.content_scroll - rows)
        elif key == curses.KEY_NPAGE:
            self.content_scroll += rows
        elif key in (27, ord("b"), ord("l")):
            self.view = "list"
            self.content_scroll = 0
        elif key == ord("n") and self.view != "next":
            self.view = "next"
            self.content_scroll = 0
        elif key == ord("s") and self.view != "stats":
            self.view = "stats"
            self.content_scroll = 0
        return True

    # ── Outreach generation ──────────────────────────────────────────────────

    def _start_generate(self) -> None:
        if not self.selected:
            return
        H, W = self.stdscr.getmaxyx()

        prompt = "  Outreach type: [r]eferral  [e]recruiter  [a]lumni  [l]inkedIn  ESC=cancel  "
        self._fill_row(H - 1, curses.color_pair(C_YELLOW) | curses.A_BOLD)
        self._safe_addstr(H - 1, 0, prompt[:W - 1], curses.color_pair(C_YELLOW) | curses.A_BOLD)
        self.stdscr.refresh()

        type_map = {"r": "referral", "e": "recruiter", "a": "alumni", "l": "linkedin"}
        raw = self.stdscr.getch()
        if raw == 27:
            self.status_msg = "Outreach cancelled."
            return
        msg_type = type_map.get(chr(raw) if 0 <= raw <= 127 else "", None)
        if not msg_type:
            self.status_msg = "Unknown type — use r/e/a/l."
            return

        try:
            subject, body = outreach_mod.generate(app=self.selected, msg_type=msg_type, cfg=self.cfg)
            outreach_mod.save_last_prompt(
                company=self.selected.company,
                msg_type=msg_type,
                contact=None,
                role=None,
                subject=subject,
                body=body,
            )
        except Exception as exc:
            self.status_msg = f"Error: {exc}"
            return

        self.outreach_lines = [f"Subject: {subject}", "─" * 50, ""] + body.splitlines()
        self.outreach_subject = subject
        self.outreach_company = self.selected.company
        self.outreach_type = msg_type
        self.content_scroll = 0
        self.view = "outreach"
        self.status_msg = "Saved to prompts/last_prompt.json  ·  c:copy"

    def _copy_outreach(self) -> None:
        if not self.outreach_lines:
            return
        text = "\n".join(self.outreach_lines)
        for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True, capture_output=True)
                self.status_msg = "Copied to clipboard."
                return
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
        self.status_msg = "Copy failed — no pbcopy/xclip/xsel found."

    def _start_resume_gen(self) -> None:
        if not self.selected:
            return
        app = self.selected
        self.status_msg = f"Generating resume for {app.company}…"
        t = threading.Thread(target=self._resume_gen_bg, args=(app,), daemon=True)
        t.start()

    def _resume_gen_bg(self, app) -> None:
        import resume_gen
        try:
            pdf_path = resume_gen.generate_resume(app, self.cfg)
            self.status_msg = f"Resume saved: {pdf_path.name}  (opening…)"
            resume_gen.open_pdf(pdf_path)
        except Exception as exc:
            self.status_msg = f"Resume error: {exc}"

    def _start_fit_assessment(self) -> None:
        if not self.selected:
            return
        app = self.selected
        self.status_msg = f"Assessing latest resume for {app.company}…"
        t = threading.Thread(target=self._fit_assessment_bg, args=(app,), daemon=True)
        t.start()

    def _fit_assessment_bg(self, app) -> None:
        try:
            report = resume_fit.assess_resume_for_app(app)
            out = resume_fit.save_report(report)
            self.fit_company = app.company
            self.fit_lines = report.to_markdown().splitlines()
            self.content_scroll = 0
            self.view = "fit"
            self.status_msg = f"Fit report saved: {out.name}"
        except Exception as exc:
            self.status_msg = f"Fit error: {exc}"

    def _show_people_searches(self) -> None:
        if not self.selected:
            return
        app = self.selected
        self.people_searches = people_finder.build_searches(app)
        self.people_company = app.company
        self.people_lines = people_finder.format_searches(app).splitlines()
        self.people_lines.append("")
        self.people_lines.append("Press 1-4 to open a search in LinkedIn. No scraping or auto-messaging.")
        self.content_scroll = 0
        self.view = "people"
        self.status_msg = "People search ready."

    def _open_url(self) -> None:
        app = self.selected
        if not app or not app.job_url:
            self.status_msg = "No URL set."
            return
        for cmd in (["open", app.job_url], ["xdg-open", app.job_url]):
            try:
                subprocess.run(cmd, check=False, capture_output=True)
                self.status_msg = f"Opened: {app.job_url[:70]}"
                return
            except FileNotFoundError:
                continue
        self.status_msg = "Could not open URL."


# ── Entry points ─────────────────────────────────────────────────────────────

def run_tui() -> None:
    try:
        curses.wrapper(_run)
    except KeyboardInterrupt:
        pass


def _run(stdscr: "curses._CursesWindow") -> None:
    tui = JobTUI(stdscr)
    tui.run()


if __name__ == "__main__":
    run_tui()
