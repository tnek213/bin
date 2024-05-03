#!/bin/bash

if [ "$#" -eq 0 ] || [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
  cat <<EOF
Usage: $(basename "$0") [options] file1 [file2 ...]

This script uses cat to display the contents of one or more files while filtering out comment lines.

Options:
  -h, --help    Show this help message and exit

Arguments:
  file1         First file to process
  file2 ...     Additional files to process (optional)

Comments are lines that begin with a # symbol. These lines are not displayed.
EOF
  exit 0
fi

cat "$@" | grep -Ev '^[[:space:]]*(//|#)|^[[:space:]]*$'
