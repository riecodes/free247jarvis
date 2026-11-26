#!/bin/sh
# macOS: one-time setup for freejarvis, safe to re-run, like setup.ps1 on Windows. Untested on macOS.
#   sh setup.sh
cd "$(dirname "$0")" || exit 1
missing=""
command -v claude >/dev/null || missing="$missing\n  - Claude Code (https://code.claude.com)"
command -v node >/dev/null || missing="$missing\n  - Node.js 20 or later (brew install node)"
py=""
for v in 3.12 3.11 3.13 3.10; do
  if command -v "python$v" >/dev/null; then py="python$v"; break; fi
done
[ -n "$py" ] || missing="$missing\n  - Python 3.10 to 3.13 (brew install python@3.12)"
if [ -n "$missing" ]; then printf "Missing:$missing\n"; exit 1; fi

set -e
[ -d .venv ] || "$py" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
npm install --silent
.venv/bin/python listener.py fetch

[ -f .env ] || cp .env.example .env
if ! grep -Eq '^GROQ_API_KEY=[^[:space:]]' .env; then
  echo 'Almost done: put your free Groq key (https://console.groq.com/keys) in .env as GROQ_API_KEY=..., then'
  echo 'run setup.sh again.'
  exit 1
fi

# Voice data (VOICE_DATA) and the other choices are asked out loud by Jarvis on its first start.
echo 'Voice packages and models are ready. (Start Jarvis with start.sh when the install is finished.)'
