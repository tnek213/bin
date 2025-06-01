#!/bin/bash

domain_perm_se() {
    local maxlen="$1"
    [[ "$maxlen" =~ ^[0-9]+$ && "$maxlen" -gt 0 ]] || {
        echo "Usage: domain_perm_se <max-length>" >&2
        return 1
    }

    # Lista av tillåtna tecken enligt .SE-regler (du kan lägga till fler om du vill)
    local chars=(
        - {0..9} {a..z}
        à á â ä å æ ç è é ê ë ì í î ï ð ñ ò ó ô õ ö ø ù ú ü ý þ
        ć č đ ě ł ń ŋ ř ś š ţ ŧ ź ž ǎ ǐ ǒ ǔ ǥ ǧ ǩ ǯ ə ʒ
        א אַ אָ ב בֿ ג ד ה ו וּ ז ח ט י ִי ך כ כּ ל ם מ ן נ ס ע ף פ פּ פֿ ץ צ ק ר ש שׂ ת תּ ײַ
    )

    chars=(
        - {0..9} {a..z}
    )

    # Omvandla tecken till en ren lista
    local charset=()
    for c in "${chars[@]}"; do
        charset+=("$c")
    done

    generate_perms() {
        local prefix="$1"
        local depth="$2"

        if (( depth == 0 )); then
            echo "${prefix}.se"
            return
        fi

        for c in "${charset[@]}"; do
            generate_perms "${prefix}${c}" $((depth - 1))
        done
    }

    for (( len = 1; len <= maxlen; len++ )); do
        generate_perms "" "$len"
    done
}

domain_perm_se "$@"
