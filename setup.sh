#!/bin/sh
# macOS: one-time setup for free247jarvis, safe to re-run, like setup.ps1 on Windows. Untested on macOS.
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
if ! grep -Eq '^(GROQ|ELEVENLABS)_API_KEY=[^[:space:]]' .env; then
  echo 'Almost done: put your free Groq key (https://console.groq.com/keys) in .env as GROQ_API_KEY=..., then'
  echo 'run setup.sh again.'
  exit 1
fi

# Off unless you say yes. With nobody there to answer (an agent, a pipe) it stays off and asks next time.
if ! grep -Eq '^VOICE_DATA=[^[:space:]]' .env; then
  echo
  echo 'Optional voice data: keep the audio and words of each request that passes the wake word, and each try it ignored, to tune how'
  echo 'Jarvis hears you, your accent and your tone. Anyone near the mic is in those clips. They stay on this Mac,'
  echo 'in ~/Library/Application Support/free247jarvis/voicedata, for 30 days. Either way, tmp/voice.log'
  echo 'keeps the words as text on this Mac. README, "Voice data".'
  printf 'Keep them? y or n (n if unsure; change it any time with VOICE_DATA in .env) '
  answer=""
  read -r answer || true
  case "$answer" in
    [Yy]*) choice=on ;;
    [Nn]*) choice=off ;;
    *) choice="" ;;
  esac
  if [ -n "$choice" ]; then
    if grep -q '^VOICE_DATA=' .env; then sed -i '' "s/^VOICE_DATA=.*/VOICE_DATA=$choice/" .env
    else printf '\nVOICE_DATA=%s\n' "$choice" >> .env; fi
    echo "VOICE_DATA=$choice saved in .env."
  else echo 'No answer: voice data stays off. Run setup.sh again to choose.'; fi
fi
echo 'Setup done. Start the boss with: sh start.sh'
