#!/usr/bin/env python3
"""Watch Simplify's Summer internship listings for the exact 🔥 company set.

Runs on GitHub Actions, sends new listings as GitHub Issues (email by watching
this repo), and persists a local seen-jobs file. Standard library only.
"""

import argparse
import ast
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/"
    "Summer2027-Internships/dev/.github/scripts/listings.json"
)
FAANG_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/"
    "Summer2027-Internships/dev/list_updater/constants.py"
)
API_ROOT = "https://api.github.com"


def load_url(url, *, headers=None, attempts=3):
    hdr = {"User-Agent": "Simplify-fire-intern-watch/1.0", "Accept": "application/json"}
    if headers:
        hdr.update(headers)
    last_exc = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_exc = exc
            if i + 1 < attempts:
                time.sleep(i + 1)
    raise RuntimeError(f"Cannot fetch {url}: {last_exc}")


def fire_companies(source):
    """Parse official FAANG_PLUS constant without running upstream Python code."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "FAANG_PLUS" for t in targets):
                value = ast.literal_eval(node.value)
                if isinstance(value, (list, set, tuple)) and value:
                    return {normalize(v) for v in value}
    raise ValueError("FAANG_PLUS not found in Simplify constants.py")


def normalize(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def structured_listings(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for name in ("listings", "jobs", "data", "results"):
            if isinstance(payload.get(name), list):
                return payload[name]
    raise ValueError("Simplify listings JSON format changed: expected array or known array key")


def company_tokens(job):
    name = str(job.get("company_name") or "")
    url = str(job.get("company_url") or "")
    slug = urllib.parse.unquote(urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1])
    return {normalize(name), normalize(slug)}


def job_key(job):
    # Prefer canonical apply URL (dedupes duplicate listings with new IDs).
    url = str(job.get("url") or "").strip()
    if url:
        # Drop URL fragments; preserve query because some ATS postings key off it.
        return urllib.parse.urldefrag(url)[0].rstrip("/")
    return str(job.get("id") or f"{job.get('company_name')}::{job.get('title')}")


def matches(job, faang, cfg):
    if not isinstance(job, dict) or job.get("active") is False or job.get("is_visible") is False:
        return False
    tokens = company_tokens(job)
    if not (tokens & faang):
        return False
    if tokens & {normalize(x) for x in cfg.get("exclude_companies", [])}:
        return False
    only = {normalize(x) for x in cfg.get("only_companies", [])}
    if only and not (tokens & only):
        return False

    title = str(job.get("title") or "").lower()
    if not any(k in title for k in ("intern", "co-op", "coop")):
        return False
    if not any(k in title for k in cfg.get("role_keywords", [])):
        return False
    if any(k in title for k in cfg.get("exclude_title_keywords", [])):
        return False

    season = cfg.get("season", "summer").lower()
    year = str(cfg.get("year", 2027))
    terms = job.get("terms") or []
    if isinstance(terms, str):
        terms = [terms]
    if terms:
        if not any(season in str(t).lower() and year in str(t) for t in terms):
            return False
    else:
        # Repo itself is summer 2027; reject explicit other terms in titles.
        if any(v in title for v in ("fall 2027", "winter 2027", "spring 2027")):
            return False
        if "2028" in title:
            return False

    loc_filters = cfg.get("location_keywords", [])
    if loc_filters:
        locs = job.get("locations") or []
        if isinstance(locs, str):
            locs = [locs]
        haystack = " ".join(str(loc) for loc in locs).lower()
        if not any(str(k).lower() in haystack for k in loc_filters):
            return False
    return True


def create_issue(token, repo, job=None, test=False):
    if not token or not repo:
        raise RuntimeError("GITHUB_TOKEN / GITHUB_REPOSITORY required to create alert issues")
    if test:
        title = "🧪 TEST: 🔥 internship email alerts are connected"
        body = (
            "This is a notification delivery test. If you got an email for this issue, "
            "GitHub email alerts are working. You can close the issue."
        )
    else:
        company = str(job.get("company_name") or "Unknown")
        title = f"🔥 {company}: {job.get('title', 'Internship')}"[:245]
        locations = job.get("locations") or []
        if isinstance(locations, str):
            locations = [locations]
        body = (
            f"**Company:** {company}  \n"
            f"**Role:** {job.get('title', '')}  \n"
            f"**Locations:** {', '.join(map(str, locations)) or 'See job posting'}  \n"
            f"**Listed date (Unix timestamp):** {job.get('date_posted', 'Unknown')}  \n"
            f"**[APPLY HERE]({job.get('url', '')})**\n\n"
            f"Source: [Simplify Summer 2027 tracker]"
            f"(https://github.com/SimplifyJobs/Summer2027-Internships). "
            f"Company is in Simplify's current FAANG_PLUS (🔥) list. "
            f"Confirm location, deadlines, sponsorship, and whether this beats your AMD offer.\n"
        )
    request = urllib.request.Request(
        f"{API_ROOT}/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body}).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Simplify-fire-intern-watch/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    print("Issue created:", result.get("html_url", title))


def run(cfg, state_path, *, token="", repo="", dry_run=False, test=False):
    if test:
        create_issue(token, repo, test=True)
        return
    faang = fire_companies(load_url(FAANG_URL))
    jobs = structured_listings(json.loads(load_url(DATA_URL)))
    matched = {job_key(job): job for job in jobs if matches(job, faang, cfg)}
    print(f"Fetched {len(jobs)} Simplify listings; {len(faang)} 🔥 companies; {len(matched)} relevant roles")
    if dry_run:
        for job in list(matched.values())[:30]:
            print(f"{job.get('company_name')} | {job.get('title')} | {job.get('url')}")
        return
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if not state_path.exists():
        state_path.write_text(json.dumps(sorted(matched), indent=2) + "\n")
        print("Bootstrapped current listings. Future new roles will trigger issues; no initial spam.")
        return
    seen = set(json.loads(state_path.read_text()))
    fresh = [(key, job) for key, job in matched.items() if key not in seen]
    print(f"Found {len(fresh)} new matching roles")
    for key, job in fresh:
        create_issue(token, repo, job)
        seen.add(key)
        # Persist after each successful notification to minimize duplicates on failures.
        state_path.write_text(json.dumps(sorted(seen), indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print today's matches, send nothing")
    parser.add_argument("--test-alert", action="store_true", help="Create a test GitHub Issue")
    args = parser.parse_args()
    cfg = json.loads((ROOT / "config.json").read_text())
    run(cfg, ROOT / "data" / "seen.json", token=os.getenv("GITHUB_TOKEN", ""),
        repo=os.getenv("GITHUB_REPOSITORY", ""), dry_run=args.dry_run,
        test=args.test_alert)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ALERT WATCHER FAILED: {exc}", file=sys.stderr)
        raise
