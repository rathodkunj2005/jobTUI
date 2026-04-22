#!/usr/bin/env python3
"""
job_fetcher.py — pull real open job listings for tracked companies.

Uses public Greenhouse / Lever / Workable JSON APIs (no auth required).
Results cached to data/job_listings.json; refreshed when > CACHE_TTL_HOURS old.

CLI:
  python job_fetcher.py                        # refresh stale cache
  python job_fetcher.py --force                # full refresh
  python job_fetcher.py --company Databricks   # one company
  python job_fetcher.py --list                 # show cached results
"""
import argparse
import concurrent.futures
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
import data as data_mod

BASE_DIR   = Path(__file__).parent
CACHE_FILE = BASE_DIR / "data" / "job_listings.json"
CACHE_TTL_HOURS = 12
FETCH_TIMEOUT   = 8
MAX_WORKERS     = 10

# ── Known ATS slugs ───────────────────────────────────────────────────────────
# Maps a substring of company name (lowercased) → (ats_type, slug)
# ats_type: "greenhouse" | "lever" | "workable"

_KNOWN: dict[str, tuple[str, str]] = {
    "databricks":      ("greenhouse", "databricks"),
    "anthropic":       ("greenhouse", "anthropic"),
    "stripe":          ("greenhouse", "stripe"),
    "figma":           ("greenhouse", "figma"),
    "coinbase":        ("greenhouse", "coinbase"),
    "airbnb":          ("greenhouse", "airbnb"),
    "roblox":          ("greenhouse", "roblox"),
    "discord":         ("greenhouse", "discord"),
    "cockroach":       ("greenhouse", "cockroachlabs"),
    "datadog":         ("greenhouse", "datadog"),
    "elastic":         ("greenhouse", "elastic"),
    "linkedin":        ("greenhouse", "linkedin"),
    "samsara":         ("greenhouse", "samsara"),
    "vercel":          ("greenhouse", "vercel"),
    "together":        ("greenhouse", "togetherai"),
    "waymo":           ("greenhouse", "waymo"),
    "robinhood":       ("greenhouse", "robinhood"),
    "dropbox":         ("greenhouse", "dropbox"),
    "twilio":          ("greenhouse", "twilio"),
    "hugging face":    ("workable",   "huggingface"),
    "scale ai":        ("greenhouse", "scaleai"),
    "scale":           ("greenhouse", "scaleai"),
    "perplexity":      ("greenhouse", "perplexityai"),
    "snowflake":       ("greenhouse", "snowflake"),
    "confluent":       ("greenhouse", "confluent"),
    "atlassian":       ("greenhouse", "atlassian"),
    "adobe":           ("greenhouse", "adobe"),
    "zoom":            ("greenhouse", "zoom"),
    "intuit":          ("greenhouse", "intuit"),
    "hubspot":         ("greenhouse", "hubspot"),
    "shopify":         ("greenhouse", "shopify"),
    "uber":            ("greenhouse", "uber"),
    "box":             ("greenhouse", "box"),
    "glean":           ("greenhouse", "glean"),
    "modal":           ("greenhouse", "modal-labs"),
    "cerebras":        ("greenhouse", "cerebras-systems"),
    "cohere":          ("greenhouse", "cohere"),
    "runway":          ("greenhouse", "runwayml"),
    "pinecone":        ("greenhouse", "pinecone-io"),
    "weaviate":        ("greenhouse", "weaviate"),
    "neon":            ("greenhouse", "neon-inc"),
    "planetscale":     ("greenhouse", "planetscale"),
    "singlestore":     ("greenhouse", "singlestore"),
    "coder":           ("greenhouse", "coder"),
    "gitlab":          ("greenhouse", "gitlab"),
    "redis":           ("greenhouse", "redis"),
    "hashicorp":       ("greenhouse", "hashicorp"),
    "palantir":        ("lever",      "palantir"),
    "anysphere":       ("lever",      "anysphere"),
    "mistral":         ("lever",      "mistral-ai"),
    "xai":             ("lever",      "xai"),
    "figure ai":       ("lever",      "figure-ai"),
    "notion":          ("lever",      "notion"),
    "replicate":       ("lever",      "replicate"),
}

# ── Role targeting ────────────────────────────────────────────────────────────

_HARD_EXCLUDE = {
    "senior", "sr.", "staff", "principal", "manager", "director",
    "vp ", " vp", "head of", "fellow", "distinguished", "lead engineer",
    "part-time", "contractor", "contract ", "architect", "president",
    "chief ", " chief", "officer", "intern", "co-op", "coop",
    "apprentice", "phd required",
}

_HARD_INCLUDE = {
    "new grad", "new-grad", "university grad", "university hire",
    "campus", "early career", "entry level", "entry-level",
    "associate engineer", "junior engineer", "associate swe",
    "0-2 years", "0-3 years",
}

_SOFT_INCLUDE = {
    "software engineer", "swe", "ml engineer", "machine learning engineer",
    "backend engineer", "systems engineer", "infrastructure engineer",
    "ai engineer", "data engineer", "platform engineer",
    "research engineer", "applied scientist", "research scientist",
    "forward deployed engineer", "applied engineer",
}

_US_SIGNALS = {
    "united states", " us ", "u.s.", "new york", "san francisco",
    "seattle", "boston", "austin", "denver", "chicago", "los angeles",
    "mountain view", "bellevue", "menlo park", "palo alto", "remote",
    "hybrid", "california", "washington", "new york city", "nyc",
}


def is_target_role(title: str, location: str = "") -> bool:
    t = title.lower()
    loc = location.lower()

    # Hard exclude
    if any(e in t for e in _HARD_EXCLUDE):
        return False

    # Location: skip if clearly non-US and not empty
    if loc and not any(s in loc for s in _US_SIGNALS):
        # Allow if location field is blank / "anywhere"
        if len(loc) > 3:
            return False

    # Hard include (e.g., "New Grad (2026)")
    if any(i in t for i in _HARD_INCLUDE):
        return True

    # Soft include
    return any(s in t for s in _SOFT_INCLUDE)


# ── ATS fetch functions ───────────────────────────────────────────────────────

def _fetch_greenhouse(slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false"
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r:
        payload = json.loads(r.read())
    results = []
    for job in payload.get("jobs", []):
        title = job.get("title", "")
        loc   = (job.get("location") or {}).get("name", "")
        if is_target_role(title, loc):
            depts = job.get("departments") or []
            results.append({
                "title":    title,
                "url":      job.get("absolute_url", ""),
                "team":     depts[0].get("name", "") if depts else "",
                "location": loc,
                "source":   "greenhouse",
            })
    return results


def _fetch_lever(slug: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=250"
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r:
        payload = json.loads(r.read())
    results = []
    for job in payload:
        title = job.get("text", "")
        cats  = job.get("categories") or {}
        loc   = cats.get("location", "")
        if is_target_role(title, loc):
            results.append({
                "title":    title,
                "url":      job.get("hostedUrl", ""),
                "team":     cats.get("team", ""),
                "location": loc,
                "source":   "lever",
            })
    return results


def _fetch_workable(slug: str) -> list[dict]:
    url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    req = urllib.request.Request(
        url,
        data=json.dumps({"query": "", "location": [], "department": [], "worktype": [], "remote": False}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
        payload = json.loads(r.read())
    results = []
    for job in payload.get("results", []):
        title = job.get("title", "")
        loc   = job.get("location", {}).get("city", "")
        country = job.get("location", {}).get("country", "")
        full_loc = f"{loc}, {country}" if country else loc
        if is_target_role(title, full_loc):
            results.append({
                "title":    title,
                "url":      f"https://apply.workable.com/{slug}/j/{job.get('shortcode', '')}",
                "team":     job.get("department", ""),
                "location": full_loc,
                "source":   "workable",
            })
    return results


def _slug_candidates(company: str) -> list[str]:
    """Auto-derive slug candidates from company name."""
    base = re.sub(r"\s*[\(\[].*?[\)\]]", "", company).strip()   # strip (parenthetical)
    base = re.sub(r"\s*/.*$", "", base).strip()                   # strip " / Segment"
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    candidates = [slug]
    nohyph = slug.replace("-", "")
    if nohyph != slug:
        candidates.append(nohyph)
    first_word = slug.split("-")[0]
    if first_word != slug:
        candidates.append(first_word)
    return candidates


def fetch_for_company(app: data_mod.Application) -> dict:
    """Try all known and derived ATS endpoints for one company. Returns a result dict."""
    name_lower = app.company.lower()

    # Look up known mapping
    ats_type, slug = None, None
    for pattern, (at, sl) in _KNOWN.items():
        if pattern in name_lower:
            ats_type, slug = at, sl
            break

    # Try known mapping first
    if ats_type and slug:
        try:
            if ats_type == "greenhouse":
                listings = _fetch_greenhouse(slug)
            elif ats_type == "lever":
                listings = _fetch_lever(slug)
            elif ats_type == "workable":
                listings = _fetch_workable(slug)
            else:
                listings = []
            return {"listings": listings, "ats": ats_type, "slug": slug, "error": None}
        except Exception as e:
            pass  # fall through to auto-guess

    # Auto-guess: try greenhouse then lever with derived slugs
    for candidate in _slug_candidates(app.company):
        for ats, fetcher in [("greenhouse", _fetch_greenhouse), ("lever", _fetch_lever)]:
            try:
                listings = fetcher(candidate)
                return {"listings": listings, "ats": ats, "slug": candidate, "error": None}
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    break
            except Exception:
                break

    return {"listings": [], "ats": None, "slug": None, "error": "not found"}


# ── Cache ─────────────────────────────────────────────────────────────────────

def load_cache() -> dict[str, dict]:
    """Return cached listings dict, or {} if missing/corrupt."""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        return raw.get("companies", {})
    except Exception:
        return {}


def cache_is_stale() -> bool:
    if not CACHE_FILE.exists():
        return True
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        fetched = datetime.fromisoformat(raw.get("fetched_at", "2000-01-01"))
        return datetime.now() - fetched > timedelta(hours=CACHE_TTL_HOURS)
    except Exception:
        return True


def save_cache(companies: dict[str, dict]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": datetime.now().isoformat(), "companies": companies}, f, indent=2)


# ── Main fetch orchestration ──────────────────────────────────────────────────

def fetch_all(
    apps: list[data_mod.Application],
    existing: Optional[dict] = None,
    force: bool = False,
    progress_cb=None,
) -> dict[str, dict]:
    """
    Fetch listings for all apps in parallel.
    existing: previously cached data (skipped unless force=True or entry missing)
    progress_cb: optional callable(company_name, result) called after each fetch
    """
    existing = existing or {}
    to_fetch = [a for a in apps if force or a.company not in existing]

    if not to_fetch:
        return existing

    results = dict(existing)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_app = {pool.submit(fetch_for_company, a): a for a in to_fetch}
        for future in concurrent.futures.as_completed(future_to_app):
            app = future_to_app[future]
            try:
                result = future.result()
            except Exception as e:
                result = {"listings": [], "ats": None, "slug": None, "error": str(e)}
            results[app.company] = result
            if progress_cb:
                progress_cb(app.company, result)

    return results


def get_listings(
    apps: list[data_mod.Application],
    force: bool = False,
) -> dict[str, dict]:
    """Main entry: load cache, fetch stale/missing entries, save, return."""
    cached = load_cache()
    if not force and not cache_is_stale():
        return cached
    updated = fetch_all(apps, existing=cached if not force else {}, force=force)
    save_cache(updated)
    return updated


# ── Convenience accessors ─────────────────────────────────────────────────────

def listing_count(results: dict[str, dict], company: str) -> int:
    return len((results.get(company) or {}).get("listings", []))


def listing_titles(results: dict[str, dict], company: str) -> list[dict]:
    return (results.get(company) or {}).get("listings", [])


# ── CLI ───────────────────────────────────────────────────────────────────────

def _fmt_count(n: int) -> str:
    return f"\033[32m{n:>3} open\033[0m" if n > 0 else "\033[2m  —\033[0m"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch real job listings for tracked companies")
    parser.add_argument("--force", action="store_true", help="Ignore cache, re-fetch everything")
    parser.add_argument("--company", metavar="NAME", help="Fetch one company only (substring match)")
    parser.add_argument("--list", action="store_true", help="Print cached results and exit")
    parser.add_argument("--filter", metavar="Q", help="Filter displayed companies by name substring")
    args = parser.parse_args()

    apps = data_mod.load()

    if args.list:
        cached = load_cache()
        q = (args.filter or "").lower()
        for company, entry in sorted(cached.items()):
            if q and q not in company.lower():
                continue
            n = len(entry.get("listings", []))
            ats = entry.get("ats") or "?"
            print(f"  {_fmt_count(n)}  {company:<45} [{ats}]")
            for job in entry.get("listings", [])[:3]:
                print(f"         • {job['title'][:60]:<60}  {job['location']}")
            if n > 3:
                print(f"         … and {n - 3} more")
        return

    if args.company:
        target = data_mod.find(apps, args.company)
        if not target:
            print(f"Company not found: {args.company}")
            sys.exit(1)
        apps = [target]

    cached = {} if args.force else load_cache()
    stale_msg = "(forced)" if args.force else "(cache stale or missing)" if cache_is_stale() else "(filling missing)"

    print(f"\033[1mFetching job listings {stale_msg}...\033[0m")
    print(f"  {len(apps)} companies  ·  up to {MAX_WORKERS} parallel connections\n")

    def on_progress(company, result):
        n = len(result.get("listings", []))
        ats = result.get("ats") or "none"
        err = result.get("error")
        if err and n == 0:
            print(f"  \033[2m—   {company[:44]:<44}  [{ats}]\033[0m")
        else:
            print(f"  {_fmt_count(n)}  {company[:44]:<44}  [{ats}]")

    updated = fetch_all(apps, existing=cached, force=args.force, progress_cb=on_progress)
    save_cache(updated)

    total = sum(len(v.get("listings", [])) for v in updated.values())
    covered = sum(1 for v in updated.values() if v.get("ats"))
    print(f"\n\033[1m{total} matching roles across {covered}/{len(updated)} companies.\033[0m")
    print(f"Cached to {CACHE_FILE}")


if __name__ == "__main__":
    main()
