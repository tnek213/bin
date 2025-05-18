#!/usr/bin/env python3
"""
check-feedback  —  classroom-repo status dashboard with caching

Usage:
    check-feedback '<glob-pattern>' <org>
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List

MENTOR = "kc8se"  # your GitHub login
CACHE_DIR = pathlib.Path("~/.cache").expanduser()


# ────────────────────────── helpers ──────────────────────────


def run(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True)


def gh_api(path: str, *, paginate: bool = False) -> str:
    cmd = ["gh", "api", path]
    if paginate:
        cmd.append("--paginate")
    return run(cmd)


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
        with cache_path(org).open("r") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(org: str, data: Dict[str, Any]) -> None:
    with cache_path(org).open("w") as fh:
        json.dump(data, fh)


# ─────────────────────────── main ────────────────────────────


def main() -> None:
    if len(sys.argv) != 3:
        sys.stderr.write(f"Usage: {sys.argv[0]} <pattern> <org>\n")
        sys.exit(1)

    glob_pat, org = sys.argv[1], sys.argv[2]
    repo_pat = re.compile("^" + re.escape(glob_pat).replace(r"\*", ".*") + "$", re.I)

    cache: Dict[str, Any] = load_cache(org)

    # 0️⃣  organisation repo list (GraphQL, auto-paginated)
    repos = json.loads(
        run(
            [
                "gh",
                "repo",
                "list",
                org,
                "--limit",
                "4000",  # high enough for a classroom cohort
                "--json",
                "name,defaultBranchRef,updatedAt",
            ]
        )
    )

    header = [
        "Repo",
        "Last Commit Author",
        "Last Commit Date",
        "Review Status",
        "Review Date",
        "Message",
    ]
    rows: List[List[str]] = [header]
    new_cache: Dict[str, Any] = {}

    for repo in repos:
        name = repo["name"]
        if not repo_pat.match(name):
            continue

        updated_at = repo["updatedAt"]
        cached = cache.get(name, {})
        if cached.get("updated_at") == updated_at:
            rows.append(cached["row"])
            new_cache[name] = cached
            sys.stderr.write(f"💾  Cached  {name}\n")
            continue

        default_branch = (repo.get("defaultBranchRef") or {}).get("name") or "main"
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
                        f"/repos/{org}/{name}/pulls/{pr_num}/reviews?per_page=100",
                        paginate=True,
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
                        f"/repos/{org}/{name}/issues/{pr_num}/comments?per_page=100",
                        paginate=True,
                    )
                )
            except subprocess.CalledProcessError:
                sys.stderr.write(
                    f"⚠️  Warning: cannot fetch comments for PR #{pr_num}\n"
                )
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
                            f"/repos/{org}/{name}/issues/comments/{c['id']}/reactions?per_page=100",
                            paginate=True,
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
                c["user"]["login"].lower() != MENTOR
                and c["created_at"] > mentor_last_seen
                for c in comments
            )
            if has_unread:
                msg_status = "Message"

        row = [name, author, commit_date, review_status, review_date, msg_status]
        rows.append(row)

        new_cache[name] = {
            "updated_at": updated_at,
            "row": row,
        }

    save_cache(org, new_cache)

    # 3️⃣  pretty-print
    col_w = [max(len(r[i]) for r in rows) for i in range(len(header))]
    for r in rows:
        print("".join(c.ljust(col_w[i] + 2) for i, c in enumerate(r)).rstrip())


if __name__ == "__main__":
    main()
