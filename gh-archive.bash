#!/usr/bin/env bash

set -euo pipefail

name="$(basename "$0")"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
CONFIG_FILE="$CONFIG_DIR/$name"

declare -a FAILS=()
report_failures() {
	if ((${#FAILS[@]})); then
		echo
		echo "Failed to archive ${#FAILS[@]} repository(ies):"
		printf '  %s\n' "${FAILS[@]}"
		exit 1
	fi
}

print_help() {
	cat <<EOF
Archive one or more GitHub repositories.

USAGE
  $name [--remote] [--help|-h] <repo>...
  $name --set-default-owner ORG

ARGS
  <repo>    Local path (default) or, with --remote, a GitHub repo or pattern.
            Remote forms accepted:
              OWNER/REPO
              OWNER/* (glob on repo name)
              REPO                   (uses default owner if set)
              *pattern*              (uses default owner if set)
              https://github.com/OWNER/REPO
              https://github.com/OWNER/*

FLAGS
  --remote              Treat <repo> as a GitHub repo or pattern instead of a local path.
  --set-default-owner   Store default OWNER/ORG for this script; must be used alone.
  -h, --help            Show help.

BEHAVIOR
  • Local: cd into each path and archive the associated GitHub repo.
  • Remote exact: archive that repo if not already archived.
  • Remote pattern with '*': list NOT-archived matches, print them, and require confirmation by typing exactly 'Y'.
  • Nothing is changed until all inputs are validated (and confirmed for patterns).
  • At the end, print a failure summary and exit non-zero if any archive failed.

EXAMPLES
  $name ./myproject
  $name --remote myorg/course-2024-lab1
  $name --remote myorg/course-2024-*         # will prompt & confirm
  $name --set-default-owner myorg
  $name --remote lab1                        # uses default owner if set
EOF
}

die() {
	echo "error: $*" >&2
	exit 1
}

normalize_remote_arg() {
	local in="$1"
	in="${in#https://github.com/}"
	in="${in#http://github.com/}"
	in="${in#git@github.com:}"
	echo "$in"
}

have_default_owner() { [[ -f "$CONFIG_FILE" ]] && [[ -s "$CONFIG_FILE" ]]; }
get_default_owner() { [[ -f "$CONFIG_FILE" ]] && sed -n '1p' "$CONFIG_FILE"; }

validate_owner_readable() {
	local owner="$1"
	if ! gh repo list "$owner" --limit 1 >/dev/null 2>&1; then
		gh api "users/$owner" >/dev/null 2>&1 || gh api "orgs/$owner" >/dev/null 2>&1 || return 1
	fi
}

is_archived_remote() {
	local slug="$1"
	gh repo view "$slug" --json isArchived -q '.isArchived' 2>/dev/null
}

list_owner_repos_json() {
	local owner="$1"
	gh repo list "$owner" --limit 1000 --json name,archived,nameWithOwner,url
}

confirm_Y() {
	local count="$1"
	echo
	echo "About to archive $count repository(ies)."
	printf "Proceed? Type 'Y' to confirm: "
	read -r ans
	[[ "$ans" == "Y" ]]
}

local_mode() {
	local -a paths=("$@")
	for p in "${paths[@]}"; do
		[[ -d "$p" ]] || die "missing path: $p"
		(cd "$p" && gh repo view --json nameWithOwner >/dev/null) || die "not a GitHub repo (no viewable remote): $p"
	done
	for p in "${paths[@]}"; do
		(
			cd "$p"
			slug="$(gh repo view --json nameWithOwner -q '.nameWithOwner' 2>/dev/null)"
			[[ -n "$slug" ]] || slug="$p"
			archived="$(gh repo view --json isArchived -q '.isArchived' 2>/dev/null || echo false)"
			if [[ "$archived" == "true" ]]; then
				echo "Already archived — skipping: $slug" >&2
				exit 0
			fi
			echo "Archiving (local): $slug" >&2
			if ! gh repo archive -y; then
				echo "Archive failed: $slug" >&2
				printf '%s\n' "$slug" >"$TMP_FAIL_ONE"
				exit 1
			fi
			exit 0
		)
		if [[ -s "${TMP_FAIL_ONE:-/dev/null}" ]]; then
			FAILS+=("$(cat "$TMP_FAIL_ONE")")
			: >"$TMP_FAIL_ONE"
		fi
	done
}

remote_mode() {
	local -a specs=("$@")
	local default_owner=""
	if have_default_owner; then default_owner="$(get_default_owner)"; fi

	local -a to_archive=()
	local -a pattern_lists=()
	local needs_confirm=false

	for raw in "${specs[@]}"; do
		local spec slug owner pat
		spec="$(normalize_remote_arg "$raw")"

		if [[ "$spec" == *'*'* ]]; then
			needs_confirm=true
			if [[ "$spec" == */* ]]; then
				owner="${spec%%/*}"
				pat="${spec#*/}"
			else
				[[ -n "$default_owner" ]] || die "pattern requires OWNER or a default owner; set one with --set-default-owner"
				owner="$default_owner"
				pat="$spec"
			fi
			[[ "$owner" != *'*'* ]] || die "owner must be explicit (no wildcards): $owner"
			validate_owner_readable "$owner" || die "cannot read owner: $owner"

			local matches
			matches="$(list_owner_repos_json "$owner" | jq -r \
				--arg pat "$pat" '
          .[] | select(.name|test("^" + ( $pat
            | gsub("\\*"; ".*") | gsub("\\?"; ".") | gsub("\\.";"\\.")
          ) + "$")) | select(.archived==false) | .nameWithOwner
        ')"
			if [[ -z "$matches" ]]; then
				pattern_lists+=("Pattern '$owner/$pat' matched 0 NOT-archived repositories.")
				continue
			fi
			pattern_lists+=("Pattern '$owner/$pat' will archive:\n$(printf '%s\n' "$matches" | sed 's/^/  /')")
			while IFS= read -r m; do [[ -n "$m" ]] && to_archive+=("$m"); done <<<"$matches"
		else
			if [[ "$spec" == */* ]]; then slug="$spec"; else
				[[ -n "$default_owner" ]] || die "missing owner for '$spec'; set default or use OWNER/REPO"
				slug="$default_owner/$spec"
			fi
			gh repo view "$slug" --json nameWithOwner >/dev/null 2>&1 || die "cannot view repo: $slug"
			if [[ "$(is_archived_remote "$slug")" != "true" ]]; then to_archive+=("$slug"); fi
		fi
	done

	if ((${#to_archive[@]})); then
		mapfile -t to_archive < <(printf '%s\n' "${to_archive[@]}" | awk '!seen[$0]++')
	fi

	if $needs_confirm; then
		printf '%s\n' "${pattern_lists[@]}" | sed '/^$/d'
		if ((${#to_archive[@]} == 0)); then
			echo "Nothing to archive." >&2
			return 0
		fi
		confirm_Y "${#to_archive[@]}" || {
			echo "Aborted by user." >&2
			return 0
		}
	fi

	for slug in "${to_archive[@]}"; do
		if [[ "$(is_archived_remote "$slug")" == "true" ]]; then
			echo "Already archived — skipping: $slug" >&2
			continue
		fi
		echo "Archiving (remote): $slug" >&2
		if ! gh repo archive "$slug" -y; then
			echo "Archive failed: $slug" >&2
			FAILS+=("$slug")
			continue
		fi
	done
}

if (($# == 0)); then
	print_help
	exit 0
fi

TMP_FAIL_ONE="$(mktemp)"
trap 'rm -f "$TMP_FAIL_ONE"' EXIT

if [[ "${1:-}" == "--set-default-owner" ]]; then
	[[ $# -eq 2 ]] || die "--set-default-owner ORG must be used alone"
	org="$2"
	validate_owner_readable "$org" || die "cannot read owner/org: $org"
	mkdir -p "$CONFIG_DIR"
	printf '%s\n' "$org" >"$CONFIG_FILE"
	echo "Default owner set to '$org' in $CONFIG_FILE"
	exit 0
fi

remote=false
declare -a args=()

while (($#)); do
	case "$1" in
	--remote)
		remote=true
		shift
		;;
	-h | --help)
		print_help
		exit 0
		;;
	--)
		shift
		while (($#)); do
			args+=("$1")
			shift
		done
		;;
	-*) die "unknown flag: $1 (use --help)" ;;
	*)
		args+=("$1")
		shift
		;;
	esac
done

((${#args[@]})) || {
	print_help
	exit 0
}

if $remote; then
	remote_mode "${args[@]}"
else
	local_mode "${args[@]}"
fi

report_failures
