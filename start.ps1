# Starts the boss: a Claude Code session named "boss" in its own Windows Terminal window, with the voice
# channel loaded. Claude Code asks you to confirm the development channel each time; pick
# "I am using this for local development". Then say "Hey Jarvis".
# The boss works in the boss folder, whose .mcp.json and CLAUDE.md only it loads.
# -Engine elevenlabs uses the pro voice for this run, whatever VOICE_ENGINE in .env says.
param([string]$Engine)
if ($Engine) { $env:VOICE_ENGINE = $Engine }
$boss = Join-Path $PSScriptRoot 'boss'

# wt.exe hands the caller's environment to the new window. Claude Code sets NO_COLOR and CLAUDE* for its
# tool shells, which would start a colorless child of that session.
Get-ChildItem env: | Where-Object Name -match '^(CLAUDE|NO_COLOR$|GIT_TERMINAL_PROMPT$)' | ForEach-Object { Remove-Item "env:$($_.Name)" }

# The first start in a folder also asks whether you trust it. Claude Code saves the answer in ~/.claude.json
# under the repo root (or the boss folder, for a ZIP download); a trusted parent such as C:\dev doesn't count.
# Node reads it: Windows PowerShell's ConvertFrom-Json fails on keys that differ only in case.
$trusted = (node -e 'try{const p=require(require(`os`).homedir()+`/.claude.json`).projects||{},k=Object.keys(p);console.log(process.argv.slice(1).some(d=>k.some(x=>x.toLowerCase()===d.replace(/\\/g,`/`).toLowerCase()&&p[x].hasTrustDialogAccepted)))}catch{console.log(false)}' $boss $PSScriptRoot) -eq 'true'

Start-Process wt.exe -ArgumentList '-w', 'new', '-d', "`"$boss`"", 'claude', '--name', 'boss',
    '--dangerously-skip-permissions', '--dangerously-load-development-channels', 'server:voice'
if (-not $trusted) {
    "First start here: in the boss window pick `"Yes, I trust this folder`" (asked only once; `"No, exit`" closes it)."
}
"Boss starting. Confirm the development channel in its window, then say `"Hey Jarvis`"."
