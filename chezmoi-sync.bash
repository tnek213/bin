#!/bin/bash

chezmoi-sync() {
  chezmoi git add .
  chezmoi git commit -- -m "$(chezmoi generate git-commit-message)"
  chezmoi git log "@..@{u}"
  chezmoi git pull
  chezmoi git log "@{u}..@"
  chezmoi git push
}

chezmoi-sync

