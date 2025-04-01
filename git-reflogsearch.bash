#!/bin/bash

if [ $# -ne 2 ]; then
	echo "Usage: $0 <pattern> <file>"
	exit 1
fi

pattern=$1
file=$2

echo "Searching for $pattern in $file in reflog:"
while read -r commit; do
	if git grep -F "$pattern" "$commit" -- "$file"; then
		echo "Found in commit: $commit"
		exit
	fi
done < <(git reflog --all | awk '{print $1}')

echo "Not found, searching in unreachable commits:"
while read -r commit; do
	if git grep -F "$pattern" "$commit" -- "$file"; then
		echo "Found in unreachable commit: $commit"
		exit
	fi
done < <(git fsck --full --no-reflogs --unreachable | grep commit | awk '{print $3}')

echo "Not found."
