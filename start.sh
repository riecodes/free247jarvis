#!/bin/sh
# macOS: starts the boss, like start.ps1 on Windows: a Claude Code session named "boss" in a new Terminal window, with
# the voice channel loaded. Pick "I am using this for local development" there, then say "Hey Jarvis". Untested on macOS.
#   sh start.sh              free voice
#   sh start.sh elevenlabs   the pro voice for this run, whatever VOICE_ENGINE in .env says
# Terminal gives claude its own terminal, so nothing here reads from /dev/tty.
cd "$(dirname "$0")" || exit 1
osascript - "$(pwd)/boss" "${1:-}" <<'EOF'
on run argv
  set boss to item 1 of argv
  set engine to item 2 of argv
  set command to "cd " & quoted form of boss & " && "
  if engine is not "" then set command to command & "VOICE_ENGINE=" & quoted form of engine & " "
  tell application "Terminal"
    activate
    do script command & "claude --name boss --dangerously-skip-permissions --dangerously-load-development-channels server:voice"
  end tell
end run
EOF
echo 'Boss starting. The first time, pick "Yes, I trust this folder"; then confirm the development channel in its window,'
echo 'allow Terminal to use the microphone when macOS asks, and say "Hey Jarvis".'
