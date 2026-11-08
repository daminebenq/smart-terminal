#!/usr/bin/env bash
# Deprecated: use ./install.sh --with-browser (or --full).
exec "$(cd "$(dirname "$0")/.." && pwd)/install.sh" --with-browser "$@"
