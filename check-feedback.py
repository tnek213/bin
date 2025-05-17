#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from datetime import datetime


def run(cmd):
    return subprocess.check_output(cmd, text=True)


def main():
    if len(sys.argv) != 3:
        sys.stderr.write(f"Usage: {sys.argv[0]} <pattern> <org>\n")
        sys.exit(1)

    pattern, org = sys.argv[1], sys.argv[2]
    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + "$"
    pat = re.compile(regex, re.IGNORECASE)

    # fetch all repos
    try:
        out = run(
            [
                "gh",
                "repo",
                "list",
                org,
                "--limit",
                "1000",
                "--json",
                "name,defaultBranchRef",
            ]
        )
        repos = json.loads(out)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"ERROR: Failed to list repos for {org}: {e}\n")
        sys.exit(1)

    # build table
    rows = [
        ["Repo", "Last Commit Author", "Last Commit Date", "Review Status", "Message"]
    ]

    for r in repos:
        name = r["name"]
        if not pat.match(name):
            continue

        default_branch = (r.get("defaultBranchRef") or {}).get("name") or "main"
        sys.stderr.write(f"⏳ Processing {name} (branch={default_branch})\n")

        # 1) latest commit
        author = "N/A"
        commit_date = "N/A"
        try:
            cj = run(["gh", "api", f"/repos/{org}/{name}/commits/{default_branch}"])
            commit = json.loads(cj)
            author = (commit.get("author") or {}).get("login") or commit["commit"][
                "author"
            ]["name"]
            iso = commit["commit"]["author"]["date"]  # e.g. "2025-05-17T01:07:13Z"
            dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
            commit_date = dt.strftime("%d/%m %H:%M")  # "17/05 01:07"
        except subprocess.CalledProcessError:
            sys.stderr.write(f"⚠️  Warning: could not fetch commit for {name}\n")

        # defaults
        review_status = "Unreviewed"
        review_time = "1970-01-01T00:00:00Z"
        msg_status = ""

        # 2) find the Classroom feedback PR (base == feedback)
        try:
            pl = run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--repo",
                    f"{org}/{name}",
                    "--base",
                    "feedback",
                    "--state",
                    "all",
                    "--json",
                    "number",
                ]
            )
            pr_list = json.loads(pl)
        except subprocess.CalledProcessError:
            sys.stderr.write(f"⚠️  Warning: cannot list PRs for {name}\n")
            pr_list = []

        if pr_list:
            pr_num = pr_list[0]["number"]
            try:
                pv = run(
                    [
                        "gh",
                        "pr",
                        "view",
                        str(pr_num),
                        "--repo",
                        f"{org}/{name}",
                        "--json",
                        "reviews,comments",
                    ]
                )
                pr_view = json.loads(pv)
            except subprocess.CalledProcessError:
                sys.stderr.write(f"⚠️  Warning: cannot fetch PR #{pr_num} for {name}\n")
                pr_view = {"reviews": [], "comments": []}

            # 2a) your latest review by kc8se
            my_revs = [
                rv
                for rv in pr_view.get("reviews", [])
                if rv.get("author", {}).get("login") == "kc8se"
            ]
            if my_revs:
                my_revs.sort(key=lambda x: x["submittedAt"])
                last = my_revs[-1]
                state = last["state"]
                if state == "APPROVED":
                    review_status = "Approved"
                elif state == "CHANGES_REQUESTED":
                    review_status = "CR"
                else:
                    review_status = "Unreviewed"
                review_time = last["submittedAt"]

            # 2b) any student comments after your review?
            new_msgs = [
                c
                for c in pr_view.get("comments", [])
                if c.get("author", {}).get("login") != "kc8se"
                and c.get("createdAt", "") > review_time
            ]
            if new_msgs:
                msg_status = "Message"

        rows.append([name, author, commit_date, review_status, msg_status])

    # 3) print aligned table
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("".join(cell.ljust(widths[i] + 2) for i, cell in enumerate(row)).rstrip())


if __name__ == "__main__":
    main()
