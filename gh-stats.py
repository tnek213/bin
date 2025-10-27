#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from subprocess import PIPE, CalledProcessError, run
from typing import Any, Dict, List, NoReturn, Optional

# ---------- paths & config ----------

PROG: str = Path(sys.argv[0]).name

CONFIG_DIR: Path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_FILE: Path = (
    CONFIG_DIR / "gh-tool-config"
)  # shared with other tools (DEFAULT_OWNER)

CACHE_DIR: Path = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
CACHE_FILE: Path = CACHE_DIR / "gh-stats.json"

# ---------- tiny gh wrapper ----------


def _gh(*args: str, cwd: Optional[Path] = None, check: bool = False) -> str:
    cp = run(["gh", *args], cwd=cwd, stdout=PIPE, stderr=PIPE, text=True)
    if check and cp.returncode != 0:
        raise CalledProcessError(cp.returncode, cp.args, cp.stdout, cp.stderr)
    return cp.stdout if cp.returncode == 0 else ""


def gh_ok(*args: str, cwd: Optional[Path] = None) -> bool:
    cp = run(["gh", *args], cwd=cwd, stdout=PIPE, stderr=PIPE, text=True)
    return cp.returncode == 0


# ---------- util ----------


def die(msg: str) -> NoReturn:
    sys.stderr.write(f"error: {msg}\n")
    raise SystemExit(1)


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


def require_default_owner(default_owner: Optional[str], msg: str) -> str:
    if default_owner is None:
        die(msg)
    return default_owner


def normalize_remote_arg(s: str) -> str:
    for p in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if s.startswith(p):
            return s[len(p) :]
    return s


# ---------- repo stats ----------


def repo_updated_at(slug: str) -> Optional[str]:
    """
    Return ISO8601 'updatedAt' from GitHub (last activity of any kind), or None on failure.
    """
    out = _gh("repo", "view", slug, "--json", "updatedAt", "--jq", ".updatedAt")
    val = out.strip()
    return val if val else None


# ---------- cache ----------


def load_cache() -> Dict[str, Any]:
    if not CACHE_FILE.exists():
        return {}
    try:
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        # Corrupt or unreadable cache — start fresh
        return {}


def save_cache(cache: Dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(CACHE_FILE)


# ---------- core ----------


def process_remotes(remotes: List[str]) -> int:
    default_owner = config_get("DEFAULT_OWNER")

    # Resolve slugs and validate existence
    slugs: list[str] = []
    for raw in remotes:
        spec = normalize_remote_arg(raw)
        if "/" in spec:
            slug = spec
        else:
            owner = require_default_owner(
                default_owner,
                f"missing owner for '{spec}'; set default or use OWNER/REPO",
            )
            slug = f"{owner}/{spec}"
        if not gh_ok("repo", "view", slug, "--json", "nameWithOwner"):
            die(f"cannot view repo: {slug}")
        slugs.append(slug)

    # Fetch updatedAt and store to cache
    cache = load_cache()
    now_iso = datetime.now(timezone.utc).isoformat()

    for slug in slugs:
        updated = repo_updated_at(slug)
        if updated is None:
            die(f"failed to retrieve updatedAt for {slug}")
        # cache structure: { "<owner>/<repo>": { "updatedAt": "...", "fetchedAt": "..." } }
        cache[slug] = {"updatedAt": updated, "fetchedAt": now_iso}

    save_cache(cache)
    return 0


# ---------- CLI ----------


def main() -> int:
    epilog = f"""\
Config:
  Uses shared config at: {CONFIG_FILE}
  Cache file: {CACHE_FILE}

Notes:
  - Repos must be remote (OWNER/REPO or REPO if DEFAULT_OWNER is set).
  - Stores the repo's last activity timestamp (updatedAt) into the cache.
  - No output on success; inspect the cache manually if desired.
"""
    ap = argparse.ArgumentParser(
        prog=PROG,
        description="Collect and cache GitHub repository stats (minimal: updatedAt).",
        epilog=epilog,
    )
    ap.add_argument(
        "--set-default-owner",
        metavar="ORG",
        help="Store default OWNER/ORG in the shared config; must be used alone.",
    )
    ap.add_argument(
        "repo",
        nargs="*",
        help="Remote repo(s): OWNER/REPO or REPO (uses DEFAULT_OWNER). Full GitHub URLs are accepted.",
    )

    args = ap.parse_args()

    # Handle default owner setter
    if args.set_default_owner is not None:
        if args.repo:
            die("--set-default-owner ORG must be used alone")
        org: str = args.set_default_owner
        # Light validation: can we 'see' this owner?
        if not (
            gh_ok("repo", "list", org, "--limit", "1")
            or gh_ok("api", f"users/{org}")
            or gh_ok("api", f"orgs/{org}")
        ):
            die(f"cannot read owner/org: {org}")
        config_set("DEFAULT_OWNER", org)
        # No output requested for stats command either; but setting defaults is a user action.
        # We'll still keep it silent to be consistent with "no output" ask.
        return 0

    if not args.repo:
        ap.print_help()
        return 0

    return process_remotes(list(args.repo))


if __name__ == "__main__":
    raise SystemExit(main())
