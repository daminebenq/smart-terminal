#!/usr/bin/env bash
# 'st' — short alias for smart-term (works from the checkout).
exec "$(cd "$(dirname "$0")" && pwd)/smart-term" "$@"
