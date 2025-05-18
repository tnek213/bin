#!/usr/bin/env python3
"""
check-feedback  —  Classroom-repo dashboard with smart caching

Columns
  ▸ Repo
  ▸ Student              (latest commit author not in AUTHOR_IGNORE_PATTERNS)
  ▸ Last Commit Date     (DD/MM HH:MM UTC — or repo creation date if all commits ignored)
  ▸ Health               (Passed / Failed / blank from combined status of latest commit)
  ▸ Review Status        (Approved / CR / Unreviewed)
  ▸ Review Date          (YYYYMMDD of most-recent mentor review)
  ▸ Message              (“Message” when student activity after mentor_last_seen)

Caching strategy
  • Row cached only if Message == "".
  • Reused next run if BOTH
        repo_updated_at  unchanged  AND
        feedback-PR updated_at unchanged.
  • New commits → repo timestamp bumps → cache invalidated.
  • New reviews / student comments → PR timestamp bumps → cache invalidated.
  • Mentor reaction clears Message flag → row wasn’t cached, so flag disappears.

Usage
    check-feedback '<glob-pattern>' <org>
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────── Configuration ────────────────────
MENTOR = "kc8se"  # your GitHub login

AUTHOR_IGNORE_PATTERNS = [
    re.compile(r"^kc8se$", re.I),
    re.compile(r"^github[-\s]?classroom(\[bot\])?$", re.I),
    re.compile(r"^dependabot(\[bot\])?$", re.I),
    # add more patterns if needed
]

CACHE_DIR = pathlib.Path("~/.cache").expanduser()
PER_PAGE = 100  # GitHub REST max page size
MESSAGE_IDX = 6  # column index of “Message” after Health column


# ─────────────────── Helper functions ─────────────────
def run(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, text=True)


def gh_api(path: str) -> str:
    return run(["gh", "api", path])


def iso_to_ddmm_hhmm(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%d/%m %H:%M")


def iso_to_yyyymmdd(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y%m%d")


def is_ignored(author: str) -> bool:
    return any(p.search(author) for p in AUTHOR_IGNORE_PATTERNS)


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


# ───── feedback-PR meta (number + updated_at) ─────
def feedback_pr_meta(org: str, repo: str) -> Tuple[Optional[int], str]:
    try:
        info = json.loads(
            gh_api(f"/repos/{org}/{repo}/pulls?state=all&base=feedback&per_page=1")
        )
        if info:
            pr = info[0]
            return pr["number"], pr["updated_at"]
    except subprocess.CalledProcessError:
        pass
    return None, ""


# ───── Build one table row (expensive) ─────
def build_row(
    org: str, repo_obj: Dict[str, Any], pr_num: Optional[int], pr_updated: str
) -> List[str]:
    name = repo_obj["name"]
    branch = repo_obj["default_branch"] or "main"
    sys.stderr.write(f"⏳ Processing {name} (branch={branch})\n")

    # Student commit & Health
    student = ""
    commit_date = iso_to_ddmm_hhmm(repo_obj["created_at"])
    health = ""
    commit_sha = None
    try:
        commits = json.loads(
            gh_api(f"/repos/{org}/{name}/commits?sha={branch}&per_page=100")
        )
        if commits:
            commit_sha = commits[0]["sha"]
        for c in commits:
            author = (c.get("author") or {}).get("login") or c["commit"]["author"][
                "name"
            ]
            if author and not is_ignored(author):
                student = author
                commit_date = iso_to_ddmm_hhmm(c["commit"]["author"]["date"])
                break
    except subprocess.CalledProcessError:
        sys.stderr.write(f"⚠️  Warning: commits fetch failed for {name}\n")

    if commit_sha:
        try:
            st = json.loads(gh_api(f"/repos/{org}/{name}/commits/{commit_sha}/status"))
            if st["statuses"]:
                health = (
                    "Passed"
                    if st["state"] == "success"
                    else "Failed"
                    if st["state"] in ("failure", "error")
                    else ""
                )
        except subprocess.CalledProcessError:
            sys.stderr.write(f"⚠️  Warning: health fetch failed for {name}\n")

    # Review / Message
    review_status, review_date, mentor_last_seen, msg_status = (
        "Unreviewed",
        "",
        "1970-01-01T00:00:00Z",
        "",
    )
    if pr_num is not None:
        try:
            reviews = json.loads(
                gh_api(
                    f"/repos/{org}/{name}/pulls/{pr_num}/reviews?per_page=100&direction=desc"
                )
            )
        except subprocess.CalledProcessError:
            reviews = []
        my_reviews = [
            rv
            for rv in reviews
            if rv.get("user", {}).get("login", "").lower() == MENTOR
        ]
        if my_reviews:
            last = max(my_reviews, key=lambda x: x["submitted_at"])
            mentor_last_seen = last["submitted_at"]
            review_date = iso_to_yyyymmdd(mentor_last_seen)
            review_status = (
                "Approved"
                if last["state"] == "APPROVED"
                else "CR"
                if last["state"] == "CHANGES_REQUESTED"
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
        if any(
            c["user"]["login"].lower() != MENTOR and c["created_at"] > mentor_last_seen
            for c in comments
        ):
            msg_status = "Message"

    return [name, student, commit_date, health, review_status, review_date, msg_status]


# ─────────────────────────── main ────────────────────────────
def main() -> None:
    if len(sys.argv) != 3:
        sys.stderr.write(f"Usage: {sys.argv[0]} <pattern> <org>\n")
        sys.exit(1)
    pattern, org = sys.argv[1], sys.argv[2]
    pat = re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + "$", re.I)

    cache, new_cache = load_cache(org), {}
    rows = [
        [
            "Repo",
            "Student",
            "Last Commit Date",
            "Health",
            "Review Status",
            "Review Date",
            "Message",
        ]
    ]

    page = 1
    while True:
        page_repos = json.loads(
            gh_api(
                f"/orgs/{org}/repos?per_page={PER_PAGE}&page={page}&sort=updated&direction=desc&type=all"
            )
        )
        if not page_repos:
            break
        may_stop = True
        for repo in page_repos:
            name = repo["name"]
            updated = repo["updated_at"]
            if not pat.match(name):
                continue
            pr_num, pr_upd = feedback_pr_meta(org, name)
            cached = cache.get(name)
            use_cached = (
                cached
                and cached.get("repo_updated_at") == updated
                and cached.get("pr_updated_at") == pr_upd
                and isinstance(cached.get("row"), list)
                and len(cached["row"]) > MESSAGE_IDX
                and cached["row"][MESSAGE_IDX] == ""
            )
            if use_cached:
                rows.append(cached["row"])
                new_cache[name] = cached
                sys.stderr.write(f"💾  Cached  {name}\n")
            else:
                row = build_row(org, repo, pr_num, pr_upd)
                rows.append(row)
                if row[MESSAGE_IDX] == "":
                    new_cache[name] = {
                        "repo_updated_at": updated,
                        "pr_updated_at": pr_upd,
                        "row": row,
                    }
                may_stop = False
        if may_stop:
            sys.stderr.write("⏹  No changes after this page — stopping pagination\n")
            break
        page += 1

    save_cache(org, new_cache)

    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("".join(c.ljust(widths[i] + 2) for i, c in enumerate(r)).rstrip())


if __name__ == "__main__":
    main()
