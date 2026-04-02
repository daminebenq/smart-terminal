#!/usr/bin/env bash
# install_bang_widget.sh
# Adds a zsh widget that intercepts lines starting with '!' and runs /usr/local/bin/smart-term

RC="$HOME/.zshrc"
MARKER="# smart_terminal: intercept lines starting with '!'
"
if grep -q "smart_term_widget" "$RC" 2>/dev/null; then
  echo "smart-term zsh widget already present in $RC"
  exit 0
fi

cat >> "$RC" <<'EOF'
# smart_terminal: intercept lines starting with '!'
_smart_term_widget() {
  if [[ $BUFFER == '!'* ]]; then
    # Remove the leading '!' and run smart-term with the remainder
    cmd="${BUFFER:1}"
    # Run smart-term in background to avoid blocking the shell prompt
    /usr/local/bin/smart-term "$cmd" &
    # clear the buffer and redraw prompt
    BUFFER=''
    zle reset-prompt
  else
    zle .accept-line
  fi
}

zle -N smart_term_widget _smart_term_widget
# bind Enter to our widget (overwrite accept-line)
bindkey '^M' smart_term_widget
EOF

echo "Appended smart-term widget to $RC. Reload your shell or run: source $RC"
