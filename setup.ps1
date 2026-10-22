# One-time setup for free247jarvis, safe to re-run: checks what it needs, installs the Python and Node
# packages, downloads the models (about 125MB), and makes .env for your Groq key.
#   powershell -ExecutionPolicy Bypass -File setup.ps1
Set-Location $PSScriptRoot
$missing = @()

$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) { $missing += 'Claude Code 2.1.234 or later (https://code.claude.com)' }
elseif ([version]((claude --version) -replace '^(\S+).*', '$1') -lt [version]'2.1.234') {
    $missing += 'a newer Claude Code (2.1.234 or later, for messaging between sessions on Windows): claude update'
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { $missing += 'Node.js 20 or later (https://nodejs.org)' }
if (-not (Get-Command wt -ErrorAction SilentlyContinue)) { $missing += 'Windows Terminal (winget install Microsoft.WindowsTerminal)' }
$py = $null
foreach ($v in '3.12', '3.11', '3.13', '3.10') {
    if ((Get-Command py -ErrorAction SilentlyContinue) -and (py "-$v" -c 'print(1)' 2>$null) -eq '1') { $py = @('py', "-$v"); break }
}
if (-not $py) { $missing += 'Python 3.10 to 3.13 (winget install Python.Python.3.11)' }
if ($missing) {
    'Missing:'
    $missing | ForEach-Object { "  - $_" }
    exit 1
}

$ErrorActionPreference = 'Stop'
if (-not (Test-Path .venv)) { & $py[0] $py[1] -m venv .venv }
.\.venv\Scripts\python -m pip install --quiet --upgrade pip
.\.venv\Scripts\python -m pip install --quiet -r requirements.txt
npm install --silent
.\.venv\Scripts\python listener.py fetch

if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if ((Get-Content .env -Raw) -notmatch 'GROQ_API_KEY=\S') {
    'Almost done: put your free Groq key (https://console.groq.com/keys) in .env as GROQ_API_KEY=..., then'
    'run setup.ps1 again.'
    exit 1
}
'Setup done. Start the boss with: powershell -ExecutionPolicy Bypass -File start.ps1'
