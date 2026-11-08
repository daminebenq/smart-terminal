#!/usr/bin/env bash
# Deprecated: shell integration (completions, Ctrl+G, `ai`) is now set up by ./install.sh.
exec "$(cd "$(dirname "$0")" && pwd)/install.sh" "$@"
