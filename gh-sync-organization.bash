#!/bin/bash

CONFIG=${XDG_CONFIG_HOME:-$HOME/.config}/gh-sync-organization

if [ -f "$CONFIG" ]; then
  # shellcheck disable=SC1090
  source "$CONFIG"
else
  ${EDITOR:-nano} "$CONFIG"
  exit
fi

set -eo pipefail

mkdir -p "$CLONE_DIR" "$BACKUP_DIR/$GH_SYNC_ORG"

stderr() {
  echo "$@" >&2
}

export -f stderr

is_connected() (
  exec &>/dev/null
  ping -q -c 1 -W 1 8.8.8.8 && [[ "$(ssh -T git@github.com 2>&1)" =~ successfully ]]
)

export -f is_connected

gh_set_default() {
  for ((i = 0; i < 5; i++)); do
    gh repo set-default "$1"
    SET_DEFAULT_EXIT_CODE=$?
    if [ "$SET_DEFAULT_EXIT_CODE" -eq 0 ]; then
      break
    fi
    stderr "Failed to set default branch, retrying..."
    sleep 5
  done
}

export -f gh_set_default

if ! is_connected; then
  stderr "Not connected to the internet or GitHub is down, skipping..."
  exit 1
fi

REPO_LIST="$(gh repo list "$GH_SYNC_ORG" --limit 4000)"

# For nice formatting
REPO_NAME_MAX_LENGTH=0
while read -r repo _; do
  [ ${#repo} -gt "$REPO_NAME_MAX_LENGTH" ] && REPO_NAME_MAX_LENGTH="${#repo}"
done <<<"$REPO_LIST"

while read -r REPO _; do
  DST="$CLONE_DIR/$REPO"
  DISPLAY_DST="${DST#"$PWD"\/}"
  printf "%-${REPO_NAME_MAX_LENGTH}s $DISPLAY_DST\n" "$REPO →"
  if [ -d "$DST" ]; then
    (
      if [ -n "$GH_SYNC_ONLY_NEW" ]; then
        stderr "Skipping $REPO, already exists"
        exit # Exit subshell
      fi
      STORED_PWD="$(pwd)"
      DISCARD=false
      cd "$DST"
      if timeout 30s git ls-remote --tags &>/dev/null; then
        if [[ -z $(timeout 10s git ls-remote --heads origin) ]]; then
            echo "⚠️  Skipping repository $(basename "$REPO") - Remote repository is empty or unreachable."
            continue
        fi

        git fetch --all --prune
        DIVERGED=$(git log --oneline --left-right "HEAD...origin/$(git branch --show-current)" || true)
        if [ -n "$DIVERGED" ]; then
          stderr "Local and remote branches have diverged"
          DISCARD=true
        else
          git fetch --all --prune
          git pull --all
        fi
      else
        DISCARD=true
      fi

      if [ "$DISCARD" = true ]; then
        stderr "Discarding local changes and re-cloning"
        SUFFIX="$(git log -1 --format=%ct)"
        cd "$STORED_PWD"
        stderr "Moving $DST to $BACKUP_DIR/$REPO-$SUFFIX"
        mv "$DST" "$BACKUP_DIR/$REPO-$SUFFIX"
        stderr "Re-cloning $REPO to $DST"
        gh repo clone "$REPO" "$DST"
        cd "$DST"
        gh_set_default "$REPO"
        git fetch --all --prune
      fi
    )
  else
    (
      stderr "Cloning $REPO to $DST"
      gh repo clone "$REPO" "$DST"
      cd "$DST"
      git fetch --all --prune

      if ! git remote -v | grep -q 'upstream'; then
        stderr "Skipping setting default as repo isn't a fork"
        exit
      fi
      gh_set_default "$REPO"
    )
  fi
done <<<"$REPO_LIST"
