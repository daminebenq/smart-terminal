#!/usr/bin/env bash
# 'st' — compact smart-terminal launcher.
# Usage:
#   st                 -> interactive CLI
#   st web_search ...  -> single-shot web_search
#   st !web_search ... -> same as above
#   st term install htop -> run !term install htop

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=${PYTHON:-python3}

if [ $# -eq 0 ]; then
  exec "$PYTHON" "$DIR/cli.py"
fi

first="$1"
shift
if [[ "$first" == '!'* ]]; then
  # user provided '!web_search' or similar as first arg
  cmd="${first:1}"
  if [ $# -gt 0 ]; then
    cmd="$cmd $*"
  fi
else
  # treat first word as the subcommand (web_search, term, do, etc.)
  cmd="!$first"
  if [ $# -gt 0 ]; then
    cmd="$cmd $*"
  fi
fi

exec "$PYTHON" "$DIR/cli.py" "$cmd"
