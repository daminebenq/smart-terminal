#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install --upgrade pip
# Install optional web-processing libraries used by smart-terminal
python3 -m pip install beautifulsoup4 trafilatura playwright selenium ddgs diskcache
# For Playwright, install browsers
python3 -m playwright install

echo "Optional web libraries installed."
