#!/bin/bash

is_valid_dot_se() {
    local domain="$1"

    # Måste sluta på .se
    [[ "$domain" =~ \.se$ ]] || return 1

    # Ta bort .se för analys
    local name="${domain%.se}"

    # Regel: inte bindestreck i både position 3 och 4
    [[ "${name:2:1}" == "-" && "${name:3:1}" == "-" ]] && return 1

    # Regel: får inte börja med bindestreck
    [[ "${name:0:1}" == "-" ]] && return 2

    # Regel: får inte ha bindestreck precis före .se
    [[ "${name: -1}" == "-" ]] && return 3

    # Avkoda Unicode-namn om det börjar med xn-- (IDN)
    if [[ "$name" =~ ^xn-- ]]; then
        name_decoded=$(printf '%s\n' "$name" | idn2 -u 2>/dev/null)
        [[ $? -ne 0 || -z "$name_decoded" ]] && return 4
    else
        name_decoded="$name"
    fi

    if echo "$name_decoded" | grep -Pq '[\x{0590}-\x{05FF}]' && echo "$name_decoded" | grep -Pq '[A-Za-z]'; then
        return 5
    fi

    # Om det är hebreiskt domännamn
    if [[ "$name_decoded" =~ [\u0590-\u05FF] ]]; then
        # Får inte börja med siffra
        [[ "${name_decoded:0:1}" =~ [0-9] ]] && return 6

        # Får inte sluta med siffra
        [[ "${name_decoded: -1}" =~ [0-9] ]] && return 7
    fi

    return 0
}

is_valid_dot_se "$@"
