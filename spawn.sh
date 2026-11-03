#!/bin/sh
# macOS: opens Claude Code workers t1 to t6, like spawn.ps1 on Windows, each in a new Terminal window. Untested on macOS.
# A name is free while no running claude has it. The windows open where Terminal puts them: no grid.
#   sh spawn.sh [count] [folder]   by default one, in the folder that holds free247jarvis
here="$(cd "$(dirname "$0")" && pwd)"
count="${1:-1}"
dir="${2:-$(dirname "$here")}"
[ -d "$dir" ] || { echo "No such folder: $dir"; exit 1; }
dir="$(cd "$dir" && pwd)"
# A worker in the boss folder would load the voice channel too and fight the boss for the microphone.
if grep -qs 'voice\.mjs' "$dir/.mcp.json"; then echo "Not in the boss folder: $dir"; exit 1; fi

opened=""
i=0
while [ "$i" -lt "$count" ]; do
  taken=" $(ps -axo command | grep -Eo -- '--name t[1-6]( |$)' | awk '{print $2}' | tr '\n' ' ') $opened "
  n=""
  for c in 1 2 3 4 5 6; do
    case "$taken" in *" t$c "*) ;; *) n=$c; break ;; esac
  done
  [ -n "$n" ] || { echo "All 6 terminals are already open."; exit 1; }
  osascript - "$dir" "t$n" <<'EOF'
on run argv
  tell application "Terminal" to do script "cd " & quoted form of (item 1 of argv) & " && claude --name " & (item 2 of argv) & " --dangerously-skip-permissions"
end run
EOF
  opened="$opened t$n"
  echo "Opened terminal $n (session t$n) in $dir."
  i=$((i + 1))
done
