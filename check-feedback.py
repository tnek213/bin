#!/usr/bin/env python3
"""
check-feedback  —  classroom-repo status dashboard
Usage:  check-feedback '<glob-pattern>' <org>
"""

import json
import re
import subprocess
import sys
from datetime import datetime

MENTOR = "kc8se"  # your GitHub login


# ────────────────────────── helpers ──────────────────────────


def run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True)


def iso_to_ddmm_hhmm(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.strftime("%d/%m %H:%M")


def iso_to_yyyymmdd(ts: str) -> str:  # ← 8-digit date
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.strftime("%Y%m%d")


def gh_api(path: str, *, paginate: bool = False) -> str:
    cmd = ["gh", "api", path]
    if paginate:
        cmd.append("--paginate")
    return run(cmd)


# ─────────────────────────── main ────────────────────────────


def main() -> None:
    if len(sys.argv) != 3:
        sys.stderr.write(f"Usage: {sys.argv[0]} <pattern> <org>\n")
        sys.exit(1)

    glob_pat, org = sys.argv[1], sys.argv[2]
    repo_pat = re.compile("^" + re.escape(glob_pat).replace(r"\*", ".*") + "$", re.I)

    repos = json.loads(
        gh_api(f"/orgs/{org}/repos?per_page=1000&sort=full_name&direction=asc")
    )

    header = [
        "Repo",
        "Last Commit Author",
        "Last Commit Date",
        "Review Status",
        "Review Date",
        "Message",
    ]
    rows: list[list[str]] = [header]

    for repo in repos:
        name = repo["name"]
        if not repo_pat.match(name):
            continue

        default_branch = repo.get("default_branch") or "main"
        sys.stderr.write(f"⏳ Processing {name} (branch={default_branch})\n")

        # 1️⃣  last commit
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

        rows.append([name, author, commit_date, review_status, review_date, msg_status])

    # 3️⃣  pretty-print
    col_w = [max(len(row[i]) for row in rows) for i in range(len(header))]
    for row in rows:
        print("".join(cell.ljust(col_w[i] + 2) for i, cell in enumerate(row)).rstrip())


if __name__ == "__main__":
    main()
