#!/bin/bash

iname="$1"
shift
find . -type f -iname "*${iname}*" "$@" 2>/dev/null
