#!/bin/bash
# Auto-commit and push any changes in /opt/sklad to GitHub. Runs via cron.
set -e
cd /opt/sklad
export GIT_SSH_COMMAND='ssh -F /root/.ssh/sklad_deploy_config'

if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m "Auto-sync $(date '+%Y-%m-%d %H:%M:%S')"
  git push -q origin main
fi
