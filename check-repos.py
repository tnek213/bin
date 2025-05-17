#!/usr/bin/env python3

import datetime
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PAGE_SIZE = 10
MATCHES = [
    re.compile(r"py-.*-i4-.*"),
    re.compile(r"python-sent-itinf23-uppgift-.*"),
    re.compile(r"pg-.*-d4-.*"),
    re.compile(r"l2-.*-i4-.*"),
    re.compile(r"i-.*-i3-.*"),
    re.compile(r"d-.*-d4-.*"),
    re.compile(r"l\d+-.*-d4-.*"),
]

state_file = Path("~/.local/share/check-repos/state.json").expanduser()
state_file.parent.mkdir(parents=True, exist_ok=True)
try:
    with state_file.open() as f:
        state = json.load(f)
    checked_after = datetime.datetime.fromisoformat(state["checked_after"])
except Exception:
    state = {}
    checked_after = datetime.datetime.fromisoformat("1970-01-01T00:00:00Z")


@dataclass
class Repo:
    name: str
    url: str
    updated_at: datetime.datetime


def fetch_repos(org):
    query = """
    query ($org: String!, $cursor: String, $page_size: Int!) {
      organization(login: $org) {
        repositories(first: $page_size, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
          nodes {
            name
            url
            updatedAt
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    """

    cursor = "null"
    while True:
        fields = [
            "-F",
            f"org={org}",
            "-F",
            f"cursor={cursor}",
            "-F",
            f"page_size={PAGE_SIZE}",
            "-F",
            f"query={query}",
        ]
        result = subprocess.run(
            ["gh", "api", "graphql"] + fields, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"GitHub API error: {result.stderr}")

        data = json.loads(result.stdout)
        repos = data["data"]["organization"]["repositories"]["nodes"]

        for repo in repos:
            yield Repo(
                name=repo["name"],
                url=repo["url"],
                updated_at=datetime.datetime.fromisoformat(repo["updatedAt"]),
            )

        page_info = data["data"]["organization"]["repositories"]["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]


def skip_repo(name):
    for match in MATCHES:
        if match.fullmatch(name):
            return False
    return True


check_start = datetime.datetime.now(datetime.timezone.utc)


def write_state():
    state["checked_after"] = check_start.isoformat()
    with state_file.open("w") as f:
        json.dump(state, f)


def prompt():
    while True:
        response = input("Continue? [n/q/w] ").lower()
        if response in ("n", "q", "w"):
            if response == "n":
                return
            else:
                if response == "w":
                    write_state()
                exit()
        else:
            print("Invalid input.")


for repo in fetch_repos("nackc8"):
    if repo.updated_at < checked_after:
        print("No changes left to check.")
        write_state()
        break
    if skip_repo(repo.name):
        continue
    print(f"Check {repo.name} ({repo.url})")
    subprocess.run(["gh", "repo", "view", "--web", repo.url])
    prompt()
