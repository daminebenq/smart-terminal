#!/usr/bin/env bash
# Deprecated: kept for backwards compatibility. Use ./install.sh (see --help).
exec "$(cd "$(dirname "$0")" && pwd)/install.sh" "$@"
