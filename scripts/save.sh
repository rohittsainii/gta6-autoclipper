#!/usr/bin/env bash
# Commit and push the given paths; retry on races with other jobs; fail loudly if it can't.
msg="$1"; shift
git config user.name "clipper-bot"
git config user.email "clipper-bot@users.noreply.github.com"
git add "$@" 2>/dev/null || true
git commit -q -m "$msg $(date -u +%F_%H%M)" || { echo "nothing to save"; exit 0; }
for i in 1 2 3 4 5 6; do
  if git pull -q --rebase && git push -q; then echo "saved"; exit 0; fi
  git rebase --abort 2>/dev/null || true
  sleep $((i * 5))
done
echo "::error::could not save results to the repo"; exit 1
