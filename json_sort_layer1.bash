#!/usr/bin/env bash

jq 'to_entries | sort_by(.key | ascii_downcase) | from_entries' "$1" >"$1".tmp && mv "$1".tmp "$1"
