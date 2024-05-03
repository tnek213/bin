#!/bin/sh

# helpline: lists summary of custom scripts

cd "$HOME/bin" || exit

{
    echo 'Script|Description'
    echo '------|-----------'
    grep -HE '^(#|//) *helpline' -- * | sed -E 's/:[^:]+: */|/' | sort
} | column --table -s '|' -o '    '
