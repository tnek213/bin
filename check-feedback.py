#!/usr/bin/env python3
"""
check-feedback — Classroom-repo dashboard (GraphQL, threaded fetch)

• Repos whose row in cache has no "Message" and identical repo.updatedAt are
  reused instantly (0 network).
• All others are fetched in parallel GraphQL calls (one per repo).
"""

from __future__ import annotations

import concurrent.futures
import json
import pathlib
import re
import subprocess
import sys
import textwrap
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ───────── configuration ─────────
MENTOR = "kc8se"
AUTHOR_IGNORE_PATTERNS = [
    re.compile(r"^kc8se$", re.I),
    re.compile(r"^github[-\\s]?classroom(\\[bot\\])?$", re.I),
    re.compile(r"^dependabot(\\[bot\\])?$", re.I),
]
CACHE_DIR = pathlib.Path("~/.cache").expanduser()
PER_PAGE = 100
MESSAGE_IDX = 6
MAX_THREADS = 12  # adjust for your bandwidth / rate-limit comfort


# ───────── helpers ─────────
def run(cmd: List[str], *, stdin: str | None = None) -> str:
    return subprocess.check_output(cmd, text=True, input=stdin)


def gh_graphql(query: str, vars: Dict[str, str]) -> Dict[str, Any]:
    args = ["gh", "api", "graphql", "-F", "query=@-"]
    for k, v in vars.items():
        args += ["-f", f"{k}={v}"]
    return json.loads(run(args, stdin=query))["data"]


def gh_rest(url: str) -> Dict[str, Any]:
    return json.loads(run(["gh", "api", url]))


def iso_to_ddmm_hhmm(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%d/%m %H:%M")


def iso_to_yyyymmdd(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y%m%d")


def is_ignored(a: str) -> bool:
    return any(p.search(a) for p in AUTHOR_IGNORE_PATTERNS)


def cache_path(org: str) -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"check-feedback-{org}.json"


def load_cache(org: str) -> Dict[str, Any]:
    try:
        return json.loads(cache_path(org).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_cache(org: str, data: Dict[str, Any]) -> None:
    cache_path(org).write_text(json.dumps(data))


# ───────── GraphQL query (one repo) ─────────
GQL_REPO = textwrap.dedent("""
query($owner:String!,$name:String!){
  repository(owner:$owner,name:$name){
    name updatedAt createdAt
    defaultBranchRef{target{... on Commit{
      history(first:20){
        nodes{
          committedDate
          author{ user{login} name }
          statusCheckRollup{ state }
        }}}}
    pullRequests(first:1,baseRefName:"feedback",
      orderBy:{field:UPDATED_AT,direction:DESC}){
      nodes{
        number updatedAt
        reviews(last:100){nodes{state submittedAt author{login}}}
        comments(first:100){
          nodes{
            createdAt author{login}
            reactions(last:100){nodes{createdAt user{login}}}
          }
        }
      }
    }
  }
}
""").strip()


# ───────── build one row (same as previous, unchanged) ─────────
def build_row(org: str, repo_data: Dict[str, Any]) -> Tuple[List[str], str, str]:
    r = repo_data["repository"]
    name, repo_upd = r["name"], r["updatedAt"]

    commits = (
        (r["defaultBranchRef"] or {})
        .get("target", {})
        .get("history", {})
        .get("nodes", [])
    )
    latest_iso = r["createdAt"]
    student = ""
    commit_date = iso_to_ddmm_hhmm(r["createdAt"])
    health = ""
    if commits:
        latest_iso = commits[0]["committedDate"]
        roll = commits[0]["statusCheckRollup"]
        if roll:
            st = roll["state"]
            health = (
                "Passed"
                if st == "SUCCESS"
                else "Failed"
                if st in ("FAILURE", "ERROR")
                else ""
            )
        for c in commits:
            author = (
                c["author"]["user"]["login"]
                if c["author"]["user"]
                else c["author"]["name"]
            )
            if author and not is_ignored(author):
                student = author
                commit_date = iso_to_ddmm_hhmm(c["committedDate"])
                break

    pr_nodes = r["pullRequests"]["nodes"]
    pr_upd = ""
    review_status = "" if student == "" else "Unreviewed"
    review_date = ""
    mentor_last = "1970-01-01T00:00:00Z"
    msg = ""
    if pr_nodes:
        pr = pr_nodes[0]
        pr_upd = pr["updatedAt"]
        my = [
            rv
            for rv in pr["reviews"]["nodes"]
            if rv["author"]["login"] and rv["author"]["login"].lower() == MENTOR
        ]
        if my:
            last = max(my, key=lambda x: x["submittedAt"])
            mentor_last = last["submittedAt"]
            review_date = iso_to_yyyymmdd(mentor_last)
            if student:
                if last["state"] == "APPROVED":
                    review_status = "Approved"
                elif last["state"] == "CHANGES_REQUESTED":
                    review_status = "Rereview" if latest_iso > mentor_last else "CR"
        comments = pr["comments"]["nodes"]
        for c in comments:
            if c["author"]["login"].lower() == MENTOR and c["createdAt"] > mentor_last:
                mentor_last = c["createdAt"]
        for c in comments:
            if c["author"]["login"].lower() == MENTOR or c["createdAt"] <= mentor_last:
                continue
            for rx in c["reactions"]["nodes"]:
                if (
                    rx["user"]["login"].lower() == MENTOR
                    and rx["createdAt"] > mentor_last
                ):
                    mentor_last = rx["createdAt"]
                    break
        if any(
            c["author"]["login"].lower() != MENTOR and c["createdAt"] > mentor_last
            for c in comments
        ):
            msg = "Message"

    return (
        [name, student, commit_date, health, review_status, review_date, msg],
        repo_upd,
        pr_upd,
    )


# ───────── main ─────────
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

    # collect repos needing fetch
    to_fetch: List[str] = []
    repo_page_num = 1
    while True:
        url = f"/orgs/{org}/repos?per_page={PER_PAGE}&page={repo_page_num}&sort=updated&direction=desc&type=all"
        page = gh_rest(url)
        if not page:
            break
        for rp in page:
            name = rp["name"]
            if not pat.match(name):
                continue
            repo_upd = rp["updated_at"]
            cached = cache.get(name)
            if (
                cached
                and cached.get("repo_updated_at") == repo_upd
                and cached["row"][MESSAGE_IDX] == ""
            ):
                rows.append(cached["row"])
                new_cache[name] = cached
                sys.stderr.write(f"💾  Cached  {name}\n")
            else:
                to_fetch.append(name)
        repo_page_num += 1

    # parallel fetch the ones we missed
    def fetch_repo(repo_name: str) -> Tuple[str, List[str], str, str]:
        data = gh_graphql(GQL_REPO, {"owner": org, "name": repo_name})
        row, repo_upd, pr_upd = build_row(org, data)
        return repo_name, row, repo_upd, pr_upd

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as ex:
        for repo_name, row, repo_upd, pr_upd in ex.map(fetch_repo, to_fetch):
            rows.append(row)
            if row[MESSAGE_IDX] == "":
                new_cache[repo_name] = {
                    "repo_updated_at": repo_upd,
                    "pr_updated_at": pr_upd,
                    "row": row,
                }

    save_cache(org, new_cache)
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("".join(c.ljust(widths[i] + 2) for i, c in enumerate(r)).rstrip())


if __name__ == "__main__":
    main()
