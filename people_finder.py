"""Safe LinkedIn people-search helpers.

We do not scrape LinkedIn or send messages automatically. This module builds
high-signal LinkedIn people-search URLs that Kunj can open, inspect, and message
manually.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

import data


@dataclass
class PeopleSearch:
    label: str
    query: str
    url: str


def linkedin_people_url(query: str) -> str:
    qs = urllib.parse.urlencode({"keywords": query})
    return f"https://www.linkedin.com/search/results/people/?{qs}"


def build_searches(app: data.Application) -> list[PeopleSearch]:
    company = app.company.split("(")[0].strip()
    role = app.role_family or app.focus or "software engineer"
    searches = [
        (f"{company} engineers", f'{company} {role} software engineer'),
        (f"{company} recruiters", f'{company} university recruiter technical recruiter software engineer'),
        (f"{company} University of Utah", f'{company} "University of Utah" software engineer'),
        (f"{company} Microsoft alumni", f'{company} Microsoft {role}'),
    ]
    return [PeopleSearch(label=label, query=query, url=linkedin_people_url(query)) for label, query in searches]


def format_searches(app: data.Application) -> str:
    lines = [f"People searches for {app.company}", ""]
    for i, s in enumerate(build_searches(app), 1):
        lines.append(f"{i}. {s.label}")
        lines.append(f"   {s.url}")
    lines.append("")
    lines.append("Use these to find: (1) someone in/near the target org, (2) a recruiter, (3) alumni/shared-background contacts.")
    return "\n".join(lines)
