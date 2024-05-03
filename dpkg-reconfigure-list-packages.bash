#!/bin/bash

debconf-get-selections | grep -v ^# | cut -f 2 | cut -d / -f 1 | sort | uniq
