# Starts the boss: a Claude Code session named "boss" in its own Windows Terminal window, with the voice
# channel loaded. Claude Code asks you to confirm the development channel each time; pick
# "I am using this for local development". Then say "Hey Claude".
# The boss works in the boss folder, whose .mcp.json and CLAUDE.md only it loads.
$boss = Join-Path $PSScriptRoot 'boss'

# wt.exe hands the caller's environment to the new window. Claude Code sets NO_COLOR and CLAUDE* for its
# tool shells, which would start a colorless child of that session.
Get-ChildItem env: | Where-Object Name -match '^(CLAUDE|NO_COLOR$|GIT_TERMINAL_PROMPT$)' | ForEach-Object { Remove-Item "env:$($_.Name)" }

Start-Process wt.exe -ArgumentList '-w', 'new', '-d', "`"$boss`"", 'claude', '--name', 'boss',
    '--dangerously-skip-permissions', '--dangerously-load-development-channels', 'server:voice'
"Boss starting. Confirm the development channel in its window, then say `"Hey Claude`"."
