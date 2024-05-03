#!/bin/bash

# helpline: list all packages that can be reconfigured with dpkg-reconfigure

debconf-get-selections | grep -v ^# | cut -f 2 | cut -d / -f 1 | sort | uniq
