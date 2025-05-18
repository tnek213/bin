#!/usr/bin/env python3
"""
check-feedback  —  classroom-repo dashboard with smart pagination & caching

Usage:
    check-feedback '<glob-pattern>' <org>
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List

MENTOR = "kc8se"  # your GitHub login
CACHE_DIR = pathlib.Path("~/.cache").expanduser()
PER_PAGE = 100  # GitHub REST max page size


# ────────────────────────── helpers ──────────────────────────


def run(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True)


def gh_api(path: str) -> str:
    return run(["gh", "api", path])


def iso_to_ddmm_hhmm(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.strftime("%d/%m %H:%M")


def iso_to_yyyymmdd(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.strftime("%Y%m%d")


# ────────────────────────── caching ──────────────────────────


def cache_path(org: str) -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"check-feedback-{org}.json"


def load_cache(org: str) -> Dict[str, Any]:
    try:
        with cache_path(org).open() as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(org: str, data: Dict[str, Any]) -> None:
    with cache_path(org).open("w") as fh:
        json.dump(data, fh)


# ───────────────────── repo-level processing ──────────────────────


def process_repo(org: str, repo: Dict[str, Any]) -> List[str]:
    """Return the table row for *repo* (and print progress to stderr)."""
    name = repo["name"]
    default_branch = repo["default_branch"] or "main"
    sys.stderr.write(f"⏳ Processing {name} (branch={default_branch})\n")

    # 1️⃣  latest commit
    author = commit_date = "N/A"
    try:
        commit = json.loads(gh_api(f"/repos/{org}/{name}/commits/{default_branch}"))
        author = (commit.get("author") or {}).get("login") or commit["commit"][
            "author"
        ]["name"]
        commit_date = iso_to_ddmm_hhmm(commit["commit"]["author"]["date"])
    except subprocess.CalledProcessError:
        sys.stderr.write(f"⚠️  Warning: could not fetch commit for {name}\n")

    review_status = "Unreviewed"
    review_date = ""
    mentor_last_seen = "1970-01-01T00:00:00Z"
    msg_status = ""

    # 2️⃣  feedback PR
    try:
        pr_list = json.loads(
            gh_api(f"/repos/{org}/{name}/pulls?state=all&base=feedback&per_page=1")
        )
    except subprocess.CalledProcessError:
        sys.stderr.write(f"⚠️  Warning: cannot list PRs for {name}\n")
        pr_list = []

    if pr_list:
        pr_num = pr_list[0]["number"]

        # reviews
        try:
            reviews = json.loads(
                gh_api(
                    f"/repos/{org}/{name}/pulls/{pr_num}/reviews?per_page=100&direction=desc"
                )
            )
        except subprocess.CalledProcessError:
            sys.stderr.write(f"⚠️  Warning: cannot fetch reviews for PR #{pr_num}\n")
            reviews = []

        my_reviews = [
            rv
            for rv in reviews
            if rv.get("user", {}).get("login", "").lower() == MENTOR
        ]
        if my_reviews:
            last_rv = max(my_reviews, key=lambda rv: rv["submitted_at"])
            mentor_last_seen = last_rv["submitted_at"]
            review_date = iso_to_yyyymmdd(mentor_last_seen)
            review_status = (
                "Approved"
                if last_rv["state"] == "APPROVED"
                else "CR"
                if last_rv["state"] == "CHANGES_REQUESTED"
                else "Unreviewed"
            )

        # comments
        try:
            comments = json.loads(
                gh_api(
                    f"/repos/{org}/{name}/issues/{pr_num}/comments?per_page=100&direction=desc"
                )
            )
        except subprocess.CalledProcessError:
            sys.stderr.write(f"⚠️  Warning: cannot fetch comments for PR #{pr_num}\n")
            comments = []

        for c in comments:
            if (
                c["user"]["login"].lower() == MENTOR
                and c["created_at"] > mentor_last_seen
            ):
                mentor_last_seen = c["created_at"]

        for c in comments:
            if (
                c["user"]["login"].lower() == MENTOR
                or c["created_at"] <= mentor_last_seen
            ):
                continue
            try:
                reactions = json.loads(
                    gh_api(
                        f"/repos/{org}/{name}/issues/comments/{c['id']}/reactions?per_page=100"
                    )
                )
            except subprocess.CalledProcessError:
                reactions = []
            for rx in reactions:
                if (
                    rx["user"]["login"].lower() == MENTOR
                    and rx["created_at"] > mentor_last_seen
                ):
                    mentor_last_seen = rx["created_at"]
                    break

        has_unread = any(
            c["user"]["login"].lower() != MENTOR and c["created_at"] > mentor_last_seen
            for c in comments
        )
        if has_unread:
            msg_status = "Message"

    return [name, author, commit_date, review_status, review_date, msg_status]


# ─────────────────────────── main ────────────────────────────


def main() -> None:
    if len(sys.argv) != 3:
        sys.stderr.write(f"Usage: {sys.argv[0]} <pattern> <org>\n")
        sys.exit(1)

    glob_pat, org = sys.argv[1], sys.argv[2]
    repo_pat = re.compile("^" + re.escape(glob_pat).replace(r"\*", ".*") + "$", re.I)

    cache: Dict[str, Any] = load_cache(org)
    new_cache: Dict[str, Any] = {}

    header = [
        "Repo",
        "Last Commit Author",
        "Last Commit Date",
        "Review Status",
        "Review Date",
        "Message",
    ]
    rows: List[List[str]] = [header]

    page = 1
    while True:
        repo_page = json.loads(
            gh_api(
                f"/orgs/{org}/repos"
                f"?per_page={PER_PAGE}&page={page}"
                f"&sort=updated&direction=desc&type=all"
            )
        )
        if not repo_page:
            break

        # Assume we might be able to stop after this page
        may_stop = True

        for repo in repo_page:
            name = repo["name"]
            if not repo_pat.match(name):
                continue

            updated_at = repo["updated_at"]
            cached = cache.get(name)
            if cached and cached["updated_at"] == updated_at:
                rows.append(cached["row"])
                new_cache[name] = cached
                sys.stderr.write(f"💾  Cached  {name}\n")
            else:
                row = process_repo(org, repo)
                rows.append(row)
                new_cache[name] = {"updated_at": updated_at, "row": row}
                # We had a cache miss → need to keep paging
                may_stop = False

        if may_stop:
            sys.stderr.write("⏹  No changes after this page — stopping pagination\n")
            break

        page += 1

    save_cache(org, new_cache)

    # print table
    col_w = [max(len(r[i]) for r in rows) for i in range(len(header))]
    for r in rows:
        print("".join(c.ljust(col_w[i] + 2) for i, c in enumerate(r)).rstrip())


if __name__ == "__main__":
    main()
