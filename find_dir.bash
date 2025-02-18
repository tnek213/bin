#!/bin/bash

iname="$1"
shift
find . -type d -iname "*${iname}*" "$@" 2>/dev/null
