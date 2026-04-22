#!/usr/bin/env python3
"""
seed_links.py — seed canonical careers-page URLs for tracker companies.

Fills blank Job URL fields with the company's main careers landing page.
Only updates rows that have an empty job_url; use --force to overwrite existing.

Usage:
  python tracker.py seed-links              # apply updates
  python tracker.py seed-links --dry-run   # preview without saving
  python tracker.py seed-links --force     # overwrite non-blank URLs too
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import data

# ── Canonical careers URLs keyed by exact company name from applications.csv ──
# Only the main careers/jobs landing page — not a deep-linked filter.
CAREERS_URLS: dict[str, str] = {
    # ── Tier 1 ─────────────────────────────────────────────────────────────
    "Databricks":                                   "https://www.databricks.com/company/careers/open-positions",
    "Microsoft (Azure AI / Foundry / Data / Copilot)": "https://careers.microsoft.com/students/us/en/",
    "NVIDIA":                                       "https://www.nvidia.com/en-us/about-nvidia/careers/",
    "Google DeepMind":                              "https://deepmind.google/about/careers/",
    "Google":                                       "https://careers.google.com/",
    "Meta":                                         "https://www.metacareers.com/",
    "Anthropic":                                    "https://www.anthropic.com/careers",
    "OpenAI":                                       "https://openai.com/careers",
    "Snowflake":                                    "https://careers.snowflake.com/",
    "Stripe":                                       "https://stripe.com/jobs",
    "Figure AI":                                    "https://www.figure.ai/careers",
    "Amazon (AWS AI / Bedrock / SageMaker / AGI)":  "https://www.amazon.jobs/en/teams/aws",
    "Apple (ML Platform / Siri / AI infra)":        "https://jobs.apple.com/",
    "Cloudflare":                                   "https://www.cloudflare.com/careers/jobs/",
    "Palantir":                                     "https://www.palantir.com/careers/",
    "Hugging Face":                                 "https://apply.workable.com/huggingface/",
    "Cohere":                                       "https://cohere.com/careers",
    "Mistral AI":                                   "https://mistral.ai/en/careers/",
    "Scale AI":                                     "https://scale.com/careers",
    "xAI":                                          "https://x.ai/careers",
    "Vercel":                                       "https://vercel.com/careers",
    "Anysphere (Cursor)":                           "https://anysphere.inc/careers",
    "MongoDB":                                      "https://www.mongodb.com/careers",
    "Replicate":                                    "https://replicate.com/careers",
    "Tesla (AI / Optimus / infra)":                 "https://www.tesla.com/careers",
    # ── Tier 2 ─────────────────────────────────────────────────────────────
    "Confluent":                                    "https://www.confluent.io/careers/",
    "Datadog":                                      "https://careers.datadoghq.com/",
    "Elastic":                                      "https://www.elastic.co/about/careers",
    "GitHub":                                       "https://www.github.careers/",
    "GitLab":                                       "https://about.gitlab.com/jobs/",
    "LinkedIn":                                     "https://careers.linkedin.com/",
    "Oracle Cloud Infrastructure":                  "https://careers.oracle.com/jobs/",
    "Redis":                                        "https://redis.io/careers/",
    "Pinecone":                                     "https://www.pinecone.io/careers/",
    "Weaviate":                                     "https://weaviate.io/company/careers",
    "Modal":                                        "https://modal.com/careers",
    "Glean":                                        "https://glean.com/careers",
    "Perplexity":                                   "https://www.perplexity.ai/hub/careers",
    "Notion":                                       "https://www.notion.so/careers",
    "Figma":                                        "https://www.figma.com/careers/",
    "Dropbox":                                      "https://jobs.dropbox.com/",
    "Box":                                          "https://www.box.com/en-us/careers",
    "Twilio / Segment":                             "https://careers.twilio.com/",
    "Shopify":                                      "https://www.shopify.com/careers",
    "Uber":                                         "https://www.uber.com/us/en/careers/",
    "Airbnb":                                       "https://careers.airbnb.com/",
    "DoorDash":                                     "https://careers.doordash.com/",
    "Samsara":                                      "https://www.samsara.com/company/careers",
    "Roblox":                                       "https://careers.roblox.com/",
    "Discord":                                      "https://discord.com/careers",
    "Coder":                                        "https://coder.com/jobs",
    "HashiCorp":                                    "https://www.hashicorp.com/careers",
    "Cockroach Labs":                               "https://www.cockroachlabs.com/careers/",
    "PlanetScale":                                  "https://planetscale.com/careers",
    "Neon":                                         "https://neon.tech/careers",
    "SingleStore":                                  "https://www.singlestore.com/careers/",
    "Snowplow":                                     "https://snowplow.io/jobs/",
    "Cerebras":                                     "https://cerebras.ai/careers/",
    "Together AI":                                  "https://www.together.ai/careers",
    "Runway":                                       "https://runwayml.com/careers/",
    "Waymo":                                        "https://waymo.com/careers/",
    # ── Tier 3 ─────────────────────────────────────────────────────────────
    "Adobe":                                        "https://careers.adobe.com/",
    "Atlassian":                                    "https://www.atlassian.com/company/careers",
    "ServiceNow":                                   "https://careers.servicenow.com/",
    "Cisco / Splunk":                               "https://jobs.cisco.com/",
    "Okta":                                         "https://www.okta.com/company/careers/",
    "VMware / Broadcom":                            "https://careers.broadcom.com/",
    "AMD":                                          "https://careers.amd.com/",
    "Qualcomm":                                     "https://careers.qualcomm.com/",
    "Intel":                                        "https://jobs.intel.com/",
    "IBM Research / watsonx":                       "https://www.ibm.com/employment/",
    "Salesforce":                                   "https://careers.salesforce.com/",
    "SAP":                                          "https://jobs.sap.com/",
    "HubSpot":                                      "https://www.hubspot.com/careers",
    "Expedia":                                      "https://careers.expedia.com/",
    "Bloomberg":                                    "https://careers.bloomberg.com/",
    "Capital One":                                  "https://www.capitalonecareers.com/",
    "JPMorgan AI / platform orgs":                  "https://careers.jpmorgan.com/",
    "Goldman Sachs":                                "https://www.goldmansachs.com/careers/",
    "Robinhood":                                    "https://careers.robinhood.com/",
    "Coinbase":                                     "https://www.coinbase.com/careers/",
    "Block / Square":                               "https://careers.block.xyz/",
    "Zoom":                                         "https://careers.zoom.us/",
    "Intuit":                                       "https://careers.intuit.com/",
    "Red Hat":                                      "https://www.redhat.com/en/jobs",
}


def seed_links(dry_run: bool = False, force: bool = False) -> list[tuple[str, str]]:
    """Update job_url fields with known careers URLs.

    Args:
        dry_run: if True, return what would change but don't write to disk.
        force:   if True, overwrite non-blank URLs too.

    Returns:
        List of (company_name, careers_url) that were (or would be) updated.
    """
    apps = data.load()
    updated: list[tuple[str, str]] = []

    for app in apps:
        if app.job_url and not force:
            continue
        url = CAREERS_URLS.get(app.company)
        if not url:
            continue
        if app.job_url == url:
            continue
        if not dry_run:
            app.job_url = url
        updated.append((app.company, url))

    if not dry_run and updated:
        data.save(apps)

    return updated


def unknown_companies() -> list[str]:
    """Return company names in the tracker that have no entry in CAREERS_URLS."""
    apps = data.load()
    return [a.company for a in apps if a.company not in CAREERS_URLS]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Seed careers URLs into tracker CSV.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--force",   action="store_true", help="Overwrite existing URLs")
    args = parser.parse_args()

    results = seed_links(dry_run=args.dry_run, force=args.force)
    if not results:
        print("Nothing to update.")
    else:
        verb = "Would update" if args.dry_run else "Updated"
        print(f"{verb} {len(results)} companies:")
        for co, url in results:
            print(f"  {co:<48} {url}")
        if args.dry_run:
            print("\n(Dry run — re-run without --dry-run to apply.)")
