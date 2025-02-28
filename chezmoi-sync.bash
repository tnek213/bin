#!/bin/bash

chezmoi-sync() {
  chezmoi git add .
  chezmoi git commit -- -m "$(chezmoi generate git-commit-message)"
  git log "@..@{u}"
  chezmoi git pull
  git log "@{u}..@"
  chezmoi git push
}

chezmoi-sync "$@"
