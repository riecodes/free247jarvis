#!/bin/sh
# macOS: starts Jarvis, like start.ps1 on Windows: a Claude Code session named "jarvis" in a new Terminal window, with
# the voice channel loaded. Pick "I am using this for local development" there, then say "Hey Jarvis". Untested on macOS.
#   sh start.sh              free voice
#   sh start.sh "" quiet     free voice, without the closing messages (the installer prints its own)
#   sh start.sh elevenlabs   the pro voice (projarvis, JARVIS_PRO in .env) for this run, whatever VOICE_ENGINE in .env says
# Terminal gives claude its own terminal, so nothing here reads from /dev/tty.
cd "$(dirname "$0")" || exit 1
osascript - "$(pwd)/jarvis" "${1:-}" <<'EOF'
on run argv
  set jarvis to item 1 of argv
  set engine to item 2 of argv
  set command to "cd " & quoted form of jarvis & " && "
  if engine is not "" then set command to command & "VOICE_ENGINE=" & quoted form of engine & " "
  tell application "Terminal"
    activate
    do script command & "claude --name jarvis --dangerously-skip-permissions --dangerously-load-development-channels server:voice"
  end tell
end run
EOF
[ "${2:-}" = quiet ] || echo 'Jarvis starting. The first time, pick "Yes, I trust this folder"; then confirm the development channel in its window,'
[ "${2:-}" = quiet ] || echo 'allow Terminal to use the microphone when macOS asks, and say "Hey Jarvis".'
