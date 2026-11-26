#!/bin/sh
# Uninstalls freejarvis: stops Jarvis and deletes this folder. Safe to run again.
#   sh uninstall.sh
dir="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$HOME" || exit 1
say() { printf '\033[36m\xf0\x9f\x92\xa0 %s\033[0m\n' "$1"; }
say 'Stopping Jarvis...'
# Its own processes: anything started from this folder, and the voice server on its port (it starts as "node ../voice.mjs").
# Only a port owner whose parent chain reaches Jarvis's own Claude session counts (see uninstall.ps1): the voice starts as "node ../voice.mjs".
port="${VOICE_PORT:-8790}"
pid="$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null | head -1)"
mine=""
p="$pid"; i=0
while [ -n "$p" ] && [ "$p" -gt 1 ] && [ $i -lt 8 ]; do
  case "$(ps -o command= -p "$p" 2>/dev/null)" in *"--name jarvis"*) mine=1; break ;; esac
  p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"; i=$((i + 1))
done
[ -n "$mine" ] && kill $pid 2>/dev/null
pkill -f "$dir" 2>/dev/null
pkill -f -- "--name jarvis" 2>/dev/null  # Jarvis's own Claude Code session, which sits in the jarvis folder
sleep 2
say "Deleting $dir ..."
rm -rf "$dir"
if [ -e "$dir" ]; then
  printf '\033[33m\xf0\x9f\x92\xa0 Some files are still in use. Close the Jarvis window, then run this again.\033[0m\n'
else
  echo
  printf '\033[32m\xf0\x9f\x92\xa0 Jarvis is uninstalled.\033[0m\n'
  echo '     Git, Python, Node.js and Claude Code stay installed: you may use them for other things.'
  echo '     Claude Code keeps its saved chats in your .claude folder.'
  echo
fi
