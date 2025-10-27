#!/usr/bin/env bash

assert_name() {
  if ! [[ "$1" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: Invalid profile name. Use only letters, numbers, underscores, or hyphens."
    exit 1
  fi
}

if [ $# -eq 1 ]; then
  PNAME="$1"
  assert_name "$PNAME"
elif [ $# -eq 2 ] && [ "$1" == "-n" ]; then
  PNAME="$2"
  assert_name "$PNAME"
  mkdir -p "$HOME/.vscode-$PNAME/user-data"
else
  echo "Usage: $0 [-n] <profile-name>"
  exit 1
fi

if [ ! -d "$HOME/.vscode-$PNAME" ]; then
  echo "Error: Profile '$PNAME' does not exist. Create it first using '-n' option."
  exit 1
fi

exec code \
  --user-data-dir="$HOME/.vscode-$PNAME/user-data" \
  --extensions-dir="$HOME/.vscode-$PNAME/extensions" \
  "$@"
