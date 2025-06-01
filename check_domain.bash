#!/bin/bash

delay=0

check_domain() {
    sleep "$delay"

    local domain="$1"

    if [[ -z "$domain" ]]; then
        echo "Usage: check_domain example.se" >&2
        return 1
    fi

    echo "Checking $domain..." >&2

    # Step 1: DNS check (non-recursive)
    if getent hosts "$domain" >/dev/null 2>&1; then
        echo "$domain is registered (resolves via DNS)" >&2
        return 0
    fi

    # Step 2: Whois check
    echo "No DNS resolution, querying whois for $domain..." >&2

    # Run whois and store result
    local whois_output
    whois_output=$(whois "$domain" 2>/dev/null)

    if grep -i -q "domain \".*\.se\" not found." <<<"$whois_output"; then
        echo "$domain appears to be free" >&2
        return 0
    elif echo "$whois_output" | grep -i -q "^registrar:"; then
        return 1
    elif echo "$whois_output" | grep -i -q "The query is not valid."; then
        return 2
    else
        echo "Most likely hit a rate limit or error with whois" >&2
        echo "$whois_output" | tee -a brute_error.log >&2
        ((delay = (delay + 1) * 2))
        echo "Retrying in $delay seconds..." >&2
        check_domain "$domain"
        return $?
    fi
}

check_domain "$1"
