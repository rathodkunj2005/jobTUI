from pathlib import Path

import data
import people_finder
import resume_fit


def test_pick_latest_resume_prefers_newest_pdf(tmp_path):
    old = tmp_path / "old.pdf"
    new = tmp_path / "new.pdf"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    old.touch()
    new.touch()
    assert resume_fit.pick_latest_resume(tmp_path) == new


def test_keyword_match_scores_overlap_and_gaps():
    resume = "Python Kubernetes distributed systems LLM RAG inference Azure"
    job = "We need Python, Kubernetes, observability, inference, distributed systems, AWS"
    result = resume_fit.keyword_match(resume, job)
    assert result["matched_keywords"][:1]
    assert "python" in result["matched_keywords"]
    assert "kubernetes" in result["matched_keywords"]
    assert "aws" in result["missing_keywords"]
    assert 0 < result["keyword_score"] < 100


def test_heuristic_assessment_has_verdict_and_actions(tmp_path):
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Python Kubernetes distributed systems LLM RAG inference Azure", encoding="utf-8")
    app = data.Application(company="Databricks", role_family="AI Infra", focus="LLM platforms", job_url="")
    report = resume_fit.assess_resume_for_app(app, resume_file, job_text="Python Kubernetes inference distributed systems observability")
    assert report.company == "Databricks"
    assert report.verdict in {"Strong interview story", "Credible interview shot", "Stretch unless tailored", "Weak fit with current resume"}
    assert report.next_actions
    assert "Databricks" in report.to_markdown()


def test_people_search_urls_are_linkedin_and_query_company():
    app = data.Application(company="Snowflake", role_family="Applied AI Engineer", focus="Data cloud")
    searches = people_finder.build_searches(app)
    assert searches
    assert all(s.url.startswith("https://www.linkedin.com/search/results/people/") for s in searches)
    assert any("Snowflake" in s.label for s in searches)
