#!/bin/bash

not_in_path() { ! command -v "$1" 1>/dev/null; }

if not_in_path dpkg; then
    exit 1
fi

if not_in_path debconf-get-selections; then
    sudo apt-get install -y debconf-utils || exit 1
fi

exit 0
