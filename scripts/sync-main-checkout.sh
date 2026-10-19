#!/bin/bash
# Puts the scheduled pipeline's own checkout at origin/main, so the daily run
# uses finalized code whatever branch the primary checkout has out. The
# checkout is a detached git worktree, which leaves `main` free to check out
# elsewhere. Private, gitignored state stays in the primary checkout and is
# linked in: one ledger, and the résumé native host is compiled to read
# config.json and attach-target-url.txt from the primary checkout.
# Usage: scripts/sync-main-checkout.sh   (prints the checkout path and commit)
set -euo pipefail

PRIMARY="${PRIMARY:-$HOME/code/job-application-agent}"
CHECKOUT="${CHECKOUT:-$HOME/code/job-application-agent-main}"
SHARED=(config.json data artifacts local-resume-companion-extension/attach-target-url.txt)

git -C "$PRIMARY" fetch --quiet origin main ||
  echo "warning: fetch failed; using the last fetched origin/main" >&2

if [ ! -e "$CHECKOUT/.git" ]; then
  git -C "$PRIMARY" worktree add --quiet --detach "$CHECKOUT" origin/main
fi
if [ -n "$(git -C "$CHECKOUT" status --porcelain --untracked-files=no)" ]; then
  echo "error: $CHECKOUT has edits to tracked files; it is pipeline-only, so leaving it for a person" >&2
  exit 1
fi
git -C "$CHECKOUT" checkout --quiet --detach origin/main

for path in "${SHARED[@]}"; do
  link="$CHECKOUT/$path"
  [ -L "$link" ] && continue
  if [ -e "$link" ]; then
    echo "error: $link exists and is not a link to $PRIMARY/$path" >&2
    exit 1
  fi
  ln -s "$PRIMARY/$path" "$link"
done

echo "pipeline checkout: $CHECKOUT at $(git -C "$CHECKOUT" log -1 --format='%h %s')"
