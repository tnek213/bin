#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from subprocess import PIPE, CalledProcessError, run
from typing import Dict, Iterable, List, NoReturn, Optional

# ------------ constants & config ------------

PROG: str = Path(sys.argv[0]).name
CONFIG_DIR: Path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_FILE: Path = CONFIG_DIR / "gh-tool-config"  # shared with other tools

# ------------ tiny gh wrapper ------------


def _gh(*args: str, cwd: Optional[Path] = None, check: bool = False) -> str:
    cp = run(["gh", *args], cwd=cwd, stdout=PIPE, stderr=PIPE, text=True)
    if check and cp.returncode != 0:
        raise CalledProcessError(cp.returncode, cp.args, cp.stdout, cp.stderr)
    return cp.stdout if cp.returncode == 0 else ""


def gh_ok(*args: str, cwd: Optional[Path] = None) -> bool:
    cp = run(["gh", *args], cwd=cwd, stdout=PIPE, stderr=PIPE, text=True)
    return cp.returncode == 0


def gh_json(*args: str, cwd: Optional[Path] = None) -> object:
    out = _gh(*args, cwd=cwd, check=True)
    return json.loads(out) if out.strip() else {}


# ------------ utilities ------------


def die(msg: str) -> NoReturn:
    sys.stderr.write(f"error: {msg}\n")
    raise SystemExit(1)


def require_default_owner(default_owner: Optional[str], msg: str) -> str:
    if default_owner is None:
        die(msg)
    return default_owner


def dedup_keep_order(seq: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ------------ config helpers ------------


def config_get(key: str) -> Optional[str]:
    if not CONFIG_FILE.exists():
        return None
    for line in CONFIG_FILE.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k == key:
                return v
    return None


def config_set(key: str, value: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = CONFIG_FILE.read_text().splitlines() if CONFIG_FILE.exists() else []
    kv = f"{key}={value}"
    for i, line in enumerate(lines):
        if line.split("=", 1)[0] == key:
            lines[i] = kv
            break
    else:
        lines.append(kv)
    CONFIG_FILE.write_text("\n".join(lines) + ("\n" if lines else ""))


# ------------ gh helpers ------------


def validate_owner_readable(owner: str) -> bool:
    return (
        gh_ok("repo", "list", owner, "--limit", "1")
        or gh_ok("api", f"users/{owner}")
        or gh_ok("api", f"orgs/{owner}")
    )


def normalize_remote_arg(s: str) -> str:
    for p in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if s.startswith(p):
            return s[len(p) :]
    return s


def is_archived_remote(slug: str) -> Optional[bool]:
    out = _gh("repo", "view", slug, "--json", "isArchived", "--jq", ".isArchived")
    if not out:
        return None
    return out.strip().lower() == "true"


def list_owner_repos(owner: str) -> List[Dict]:
    data = gh_json(
        "repo",
        "list",
        owner,
        "--limit",
        "1000",
        "--json",
        "name,archived,nameWithOwner,url",
    )
    if isinstance(data, list):
        return data  # type: ignore[return-value]
    return []


# ------------ core ------------


@dataclass
class Plan:
    to_archive: List[str]
    messages: List[str]
    needs_confirm: bool


def plan_remote(specs: List[str], default_owner: Optional[str]) -> Plan:
    to_archive: List[str] = []
    messages: List[str] = []
    needs_confirm = False

    for raw in specs:
        spec = normalize_remote_arg(raw)

        if "*" in spec:  # pattern mode
            needs_confirm = True
            if "/" in spec:
                owner, pat = spec.split("/", 1)
            else:
                owner = require_default_owner(
                    default_owner, "pattern requires OWNER or DEFAULT_OWNER"
                )
                pat = spec
            if "*" in owner:
                die(f"owner must be explicit (no wildcards): {owner}")
            if not validate_owner_readable(owner):
                die(f"cannot read owner: {owner}")

            matches: List[str] = [
                str(r.get("nameWithOwner", ""))
                for r in list_owner_repos(owner)
                if not r.get("archived", False) and fnmatch(str(r.get("name", "")), pat)
            ]
            matches = [m for m in matches if m]
            if matches:
                messages.append(
                    f"Pattern '{owner}/{pat}' will archive:\n"
                    + "\n".join(f"  {m}" for m in matches)
                )
                to_archive.extend(matches)
            else:
                messages.append(
                    f"Pattern '{owner}/{pat}' matched 0 NOT-archived repositories."
                )
        else:  # exact slug (owner may be omitted)
            if "/" in spec:
                slug: str = spec
            else:
                owner = require_default_owner(
                    default_owner,
                    f"missing owner for '{spec}'; set default or use OWNER/REPO",
                )
                slug = f"{owner}/{spec}"
            if not gh_ok("repo", "view", slug, "--json", "nameWithOwner"):
                die(f"cannot view repo: {slug}")
            archived = is_archived_remote(slug)
            if archived is None:
                die(f"cannot view repo: {slug}")
            if not archived:
                to_archive.append(slug)

    to_archive = dedup_keep_order(to_archive)
    return Plan(to_archive, messages, needs_confirm)


def confirm(count: int, verb: str = "archive") -> bool:
    print()
    print(f"About to {verb} {count} repository(ies).")
    return input("Proceed? Type 'Y' to confirm: ").strip() == "Y"


def archive_remote(specs: List[str]) -> int:
    default_owner = config_get("DEFAULT_OWNER")
    plan = plan_remote(specs, default_owner)

    if plan.needs_confirm:
        print("\n".join(m for m in plan.messages if m.strip()))
        if not plan.to_archive:
            sys.stderr.write("Nothing to archive.\n")
            return 0
        if not confirm(len(plan.to_archive), "archive"):
            sys.stderr.write("Aborted by user.\n")
            return 0

    fails: List[str] = []
    for slug in plan.to_archive:
        archived_now = is_archived_remote(slug)
        if archived_now is True:
            sys.stderr.write(f"Already archived — skipping: {slug}\n")
            continue
        sys.stderr.write(f"Archiving (remote): {slug}\n")
        if not gh_ok("repo", "archive", slug, "-y"):
            sys.stderr.write(f"Archive failed: {slug}\n")
            fails.append(slug)

    if fails:
        print(f"\nFailed to archive {len(fails)} repository(ies):")
        print("\n".join(f"  {s}" for s in fails))
        return 1
    return 0


def archive_local(paths: List[str]) -> int:
    # validate first
    for p in paths:
        pp = Path(p)
        if not pp.is_dir():
            die(f"missing path: {p}")
        if not gh_ok("repo", "view", "--json", "nameWithOwner", cwd=pp):
            die(f"not a GitHub repo (no viewable remote): {p}")

    fails: List[str] = []
    for p in paths:
        pp = Path(p)
        slug_out = _gh(
            "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner", cwd=pp
        ).strip()
        slug = slug_out if slug_out else p
        archived_out = (
            _gh("repo", "view", "--json", "isArchived", "--jq", ".isArchived", cwd=pp)
            .strip()
            .lower()
        )
        archived = archived_out == "true"
        if archived:
            sys.stderr.write(f"Already archived — skipping: {slug}\n")
            continue
        sys.stderr.write(f"Archiving (local): {slug}\n")
        if not gh_ok("repo", "archive", "-y", cwd=pp):
            sys.stderr.write(f"Archive failed: {slug}\n")
            fails.append(slug)

    if fails:
        print(f"\nFailed to archive {len(fails)} repository(ies):")
        print("\n".join(f"  {s}" for s in fails))
        return 1
    return 0


# ------------ CLI ------------


def main() -> int:
    epilog = f"""\
Config:
  Uses shared config at: {CONFIG_FILE}
  Stored keys:
    DEFAULT_OWNER   Owner/organization used when OWNER is omitted.

Remote forms accepted:
  OWNER/REPO
  OWNER/*             (glob on repo name)
  REPO                (uses DEFAULT_OWNER if set)
  *pattern*           (uses DEFAULT_OWNER if set)
  https://github.com/OWNER/REPO
  https://github.com/OWNER/*

Examples:
  {PROG} ./myproject
  {PROG} --remote myorg/course-2024-lab1
  {PROG} --remote myorg/course-2024-*         # will prompt & confirm
  {PROG} --set-default-owner myorg
  {PROG} --remote lab1                        # uses DEFAULT_OWNER if set
"""
    ap = argparse.ArgumentParser(
        prog=PROG,
        description="Archive one or more GitHub repositories.",
        epilog=epilog,
    )
    ap.add_argument(
        "--remote",
        action="store_true",
        help="Treat <repo> as a GitHub repo or pattern instead of a local path.",
    )
    ap.add_argument(
        "--set-default-owner",
        metavar="ORG",
        help="Store default OWNER/ORG in the shared config; must be used alone.",
    )
    ap.add_argument(
        "repo",
        nargs="*",
        help="Local path(s) or, with --remote, repo or pattern(s).",
    )

    args = ap.parse_args()

    if args.set_default_owner is not None:
        if args.remote or args.repo:
            die("--set-default-owner ORG must be used alone")
        org: str = args.set_default_owner
        if not validate_owner_readable(org):
            die(f"cannot read owner/org: {org}")
        config_set("DEFAULT_OWNER", org)
        print(f"Default owner set to '{org}' in {CONFIG_FILE}")
        return 0

    if not args.repo:
        ap.print_help()
        return 0

    return (
        archive_remote(list(args.repo))
        if args.remote
        else archive_local(list(args.repo))
    )


if __name__ == "__main__":
    raise SystemExit(main())
