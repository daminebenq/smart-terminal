#!/usr/bin/env bash
# Adds a convenient shell function 'term' to ~/.zshrc if not present
set -euo pipefail
RCFILE=${ZSHRC:-$HOME/.zshrc}
SNIPPET="\n# smart-terminal convenience function\nterm() { python3 /Users/damine/smart-terminal/cli.py \"\$*\"; }\n"
if grep -q "smart-terminal convenience function" "$RCFILE" 2>/dev/null; then
  echo "term() function already present in $RCFILE"
else
  echo -e "$SNIPPET" >> "$RCFILE"
  echo "Appended term() function to $RCFILE. Run 'source $RCFILE' or open a new shell to use it."
fi
