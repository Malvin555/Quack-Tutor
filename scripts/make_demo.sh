#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
WORK="$(mktemp -d)"
cp -r tests/fixtures/mini_repo/. "$WORK"
Q="why does session_valid reject valid sessions?"
quack -C "$WORK" ask "$Q" "$@"
quack -C "$WORK" ask "$Q" "$@"            # second run should say: cached, 0 tokens
quack -C "$WORK" explain auth.py "$@" || true
quack -C "$WORK" verify
quack -C "$WORK" history > /dev/null
quack -C "$WORK" export -o .quack/session.log
cp "$WORK/TASKS.md" "$WORK/QUACK_HISTORY.md" demo/
cp "$WORK/.quack/session.log" demo/session.log
echo "Wrote demo/TASKS.md, demo/QUACK_HISTORY.md, demo/session.log from a real run."
