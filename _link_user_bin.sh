#!/bin/sh

# shellcheck shell=sh

# Function to display help
show_help() {
  cat <<EOF
Usage: $(basename "$0") [source_dir destination_dir]

This command hard links script files from the source directory to the destination directory, removing their programming language suffix.

Arguments:
  source_dir       The directory where the script files are located.
  destination_dir  The directory where the script files will be linked without suffixes.

The command prioritizes directories as follows:
1. Command line arguments (if two arguments are passed).
2. Environment variables LINKBIN_SRC and LINKBIN_DST if defined.
3. Fallback defaults: source \$HOME/.bin and destination \$HOME/bin.

Recognized script suffixes such as .sh for shell scripts, .py for Python scripts, etc., are removed in the destination directory.
EOF
}

# Check for help request
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
  show_help
  exit 0
fi

# Determine source and destination directories
if [ "$#" -eq 2 ]; then
  SOURCE_DIR="$1"
  DESTINATION_DIR="$2"
elif [ -n "$LINKBIN_SRC" ] && [ -n "$LINKBIN_DST" ]; then
  SOURCE_DIR="$LINKBIN_SRC"
  DESTINATION_DIR="$LINKBIN_DST"
else
  SOURCE_DIR="$HOME/.config/home_bin"
  DESTINATION_DIR="$HOME/bin"
fi

# Ensure both directories are valid
if [ ! -d "$SOURCE_DIR" ] || [ ! -d "$DESTINATION_DIR" ]; then
  echo "Error: One or both specified directories do not exist of '$SOURCE_DIR' and '$DESTINATION_DIR'."
  show_help
  exit 1
fi

for SETUP_SCRIPT in "$SOURCE_DIR"/.*; do
  case $(basename "$SETUP_SCRIPT") in
  . | .. | .git | .gitignore)
    continue
    ;;
  esac

  SRC="$(dirname "$SETUP_SCRIPT")/$(basename "$SETUP_SCRIPT" | cut -c 2-)"

  if [ ! -e "$SRC" ]; then
    echo "Error: Skipping setup script '$SETUP_SCRIPT' as the corresponding script '$SRC' does not exist" 1>&2
    exit 1
  fi

  if [ ! -x "$SRC" ]; then
    echo "Error: Skipping setup script '$SETUP_SCRIPT' as the corresponding script '$SRC' is not executable" 1>&2
    exit 1
  fi
done

in_path() { command -v "$1" 1>/dev/null; }

# Script linking logic here

for PAIR in "bash,#!/bin/bash" "sh,#!/bin/sh" "py,#!/usr/bin/env python3"; do
  SUFFIX=${PAIR%,*}
  SHEBANG_LINE=${PAIR#*,}
  SHEBANG_PATH=${PAIR#*\#\!}
  SHEBANG_PATH=${SHEBANG_PATH% *}
  if ! in_path "$SHEBANG_PATH"; then
    echo "Warning: Skipping ALL '*.$SUFFIX' files as '$SHEBANG_PATH' isn't in \$PATH" 1>&2
    continue
  fi

  for SRC in "$SOURCE_DIR/"*."$SUFFIX"; do
    [ ! -f "$SRC"  ] && echo "No *.$SUFFIX files" >&2 && continue

    EXECUTABLE=$(basename "$SRC")
    EXECUTABLE=${EXECUTABLE%%."$SUFFIX"}
    SETUP_SCRIPT="$(dirname "$SRC")/.$(basename "$SRC")"

    # do not link files prefixed with double underscores
    if [ "$(echo "$EXECUTABLE" | cut -c1-1)" = "__" ]; then
      continue
    fi

    if ! [ -x "$SRC" ]; then
      echo "Warning: Skipping non executable '$SRC'" 1>&2
      continue
    fi

    if [ "$(head -n 1 "$SRC")" != "$SHEBANG_LINE" ]; then
      echo "Warning: Skipping '$SRC' as it has a malformed or missing shebang" 1>&2
      continue
    fi

    DST="$DESTINATION_DIR/$EXECUTABLE"

    if [ -e "$DST" ]; then
      SRC_ID=$(stat -c '%d:%i' "$SRC")
      DST_ID=$(stat -c '%d:%i' "$DST")
      if [ "$SRC_ID" != "$DST_ID" ]; then
        echo "Warning: Both source '$SRC' and destination '$DST' exists but are different files!" 1>&2
      fi
      continue
    fi

    if [ -z "$MSG_SHOWN" ]; then
      echo "Linking files from $SOURCE_DIR to $DESTINATION_DIR..." 1>&2
      MSG_SHOWN='true'
    fi
    if [ -e "$SETUP_SCRIPT" ]; then
      "$SETUP_SCRIPT" && ln -v "$SRC" "$DST"
    else
      ln -v "$SRC" "$DST"
    fi
  done
done
