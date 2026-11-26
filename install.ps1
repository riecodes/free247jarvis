# One-line install of freejarvis on Windows, safe to run again (it updates):
#   irm webinar.riecodes.com/jarvis.ps1 | iex
# Installs what is missing (Git, Python 3.11, Node LTS, Windows Terminal, Claude Code), clones or updates
# freejarvis in %USERPROFILE%\freejarvis, asks for your free Groq key once, runs setup.ps1, installs the window,
# then starts Jarvis, who greets you and asks the rest out loud.
# For testing: JARVIS_DIR (folder), JARVIS_BRANCH (git branch), JARVIS_GROQ_KEY (skips the key prompt),
# JARVIS_NO_WINDOW=1 (skips the Electron window, about 250 MB), JARVIS_NO_START=1 (installs without starting).
# Keep this file ASCII: Windows PowerShell 5.1 runs it.
& {
  $ErrorActionPreference = 'Continue'
  try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
  $gem = [char]::ConvertFromUtf32(0x1F4A0)
  $bin = Join-Path $env:USERPROFILE '.local\bin'
  $dir = if ($env:JARVIS_DIR) { $env:JARVIS_DIR } else { Join-Path $env:USERPROFILE 'freejarvis' }
  $branch = if ($env:JARVIS_BRANCH) { $env:JARVIS_BRANCH } else { 'main' }
  function Say([string]$text, [string]$color = 'Cyan') { Write-Host "$gem $text" -ForegroundColor $color }
  function Fail([string]$text) { Write-Host "$gem $text" -ForegroundColor Red }
  # New installs land in the registry, not in this window: reload PATH from there before every look.
  function Has([string]$name) {
    $env:Path = "$bin;" + [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    [bool](Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*\WindowsApps\claude.exe' })
  }
  # py -0 lists the installed Pythons; asking py for one that is not there prints red errors in Windows PowerShell 5.1.
  function HasPython {
    if (-not (Has 'py')) { return $false }
    $old = $ErrorActionPreference; $ErrorActionPreference = 'SilentlyContinue'
    $list = (py -0 2>&1 | Out-String)
    $ErrorActionPreference = $old
    [bool]($list -match '(-V:|-)3\.(10|11|12|13)\b')
  }
  function Winget([string]$id, [string]$label) {
    if (-not (Has 'winget')) { Fail "Can't install $label without WinGet. Install it from the Microsoft Store (App Installer), then run this again."; return }
    Say "Installing $label..."
    winget install --id $id -e --source winget --silent --accept-package-agreements --accept-source-agreements | Out-Host
  }

  Write-Host ''
  Say 'Jarvis installer' 'White'
  Say "Folder: $dir" 'DarkCyan'

  # 1. Tools
  if (-not (Has 'git')) { Winget 'Git.Git' 'Git' }
  if (-not (HasPython)) { Winget 'Python.Python.3.11' 'Python 3.11' }
  if (-not (Has 'node')) { Winget 'OpenJS.NodeJS.LTS' 'Node.js LTS' }
  if (-not (Has 'wt')) { Winget 'Microsoft.WindowsTerminal' 'Windows Terminal' }
  $missing = @()
  if (-not (Has 'git')) { $missing += 'Git' }
  if (-not (HasPython)) { $missing += 'Python 3.10 to 3.13' }
  if (-not (Has 'node')) { $missing += 'Node.js' }
  if (-not (Has 'wt')) { $missing += 'Windows Terminal' }
  if ($missing) { Fail ("Still missing: " + ($missing -join ', ') + '. Close this window, open a new PowerShell, and run the line again.'); return }

  # 2. Claude Code
  if (-not (Has 'claude')) {
    Say 'Installing Claude Code. About 1 to 3 minutes, with no progress bar while it downloads.'
    # Its own process, so an exit inside the official installer can't close this window.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = 'Tls12'; irm https://claude.ai/install.ps1 | iex"
    if (-not (Has 'claude') -and (Has 'winget')) { winget install --id Anthropic.ClaudeCode -e --source winget --accept-package-agreements --accept-source-agreements | Out-Host }
    if (-not (Has 'claude')) { Fail 'Claude Code did not install. Try: irm https://claude.ai/install.ps1 | iex, then run this line again.'; return }
    # New windows (the Jarvis window too) need claude on the user PATH.
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ((Test-Path (Join-Path $bin 'claude.exe')) -and ($userPath -split ';') -notcontains $bin) {
      [Environment]::SetEnvironmentVariable('Path', "$bin;$userPath", 'User')
    }
  } else {
    $version = [version]((claude --version 2>$null | Select-Object -First 1) -replace '^(\d+(\.\d+)+).*', '$1')
    if ($version -lt [version]'2.1.234') { Say 'Updating Claude Code (Jarvis needs 2.1.234 or later)...'; claude update | Out-Host }
  }
  Say ('Claude Code ' + (claude --version 2>$null | Select-Object -First 1)) 'Green'

  # 3. Get or update freejarvis
  if (Test-Path (Join-Path $dir '.git')) {
    Say 'Updating freejarvis...'
    git -C $dir pull --ff-only --quiet
    if ($LASTEXITCODE -ne 0) { Say 'Could not update (local changes?). Going on with the copy you have.' 'Yellow' }
  } elseif (Test-Path $dir) {
    Fail "$dir exists but is not a freejarvis clone. Move it away (or set JARVIS_DIR) and run this again."; return
  } else {
    Say 'Downloading freejarvis...'
    git clone --quiet --branch $branch https://github.com/riecodes/freejarvis.git $dir
    if ($LASTEXITCODE -ne 0) { Fail 'Download failed. Check your internet and run this again.'; return }
  }
  Push-Location $dir

  # 4. Groq key (free, no card): the only thing you type.
  $envFile = Join-Path $dir '.env'
  if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $dir '.env.example') $envFile }
  $text = [IO.File]::ReadAllText($envFile)
  if ($text -notmatch '(?m)^GROQ_API_KEY=\S') {
    $key = "$env:JARVIS_GROQ_KEY".Trim()
    if (-not $key) {
      Say 'Jarvis hears you through Groq, which is free (no card). Opening the Groq keys page: sign in, Create API Key, copy it.'
      Start-Process 'https://console.groq.com/keys'
    }
    while ($key -notmatch '^gsk_\S{20,}$') {
      if ($key) { Say 'That does not look like a Groq key (it starts with gsk_). Try again.' 'Yellow' }
      try { $key = (Read-Host "$gem Paste your Groq key here and press Enter").Trim() } catch { $key = '' }
      if (-not $key) { Fail 'No key given. Run this line again when you have it.'; return }
    }
    try {
      Invoke-RestMethod 'https://api.groq.com/openai/v1/models' -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 15 | Out-Null
    } catch {
      $code = try { [int]$_.Exception.Response.StatusCode } catch { 0 }
      if ($code -eq 401) { Fail 'Groq says that key is not valid. Make a new one and run this line again.'; return }
    }
    if ($text -match '(?m)^GROQ_API_KEY=') { $text = $text -replace '(?m)^GROQ_API_KEY=.*$', "GROQ_API_KEY=$key" }
    else { $text = $text.TrimEnd() + "`r`nGROQ_API_KEY=$key`r`n" }
    [IO.File]::WriteAllText($envFile, $text)
    Say 'Groq key saved in .env.' 'Green'
  }

  # 5. Setup: Python and Node packages, models (a few hundred MB the first time).
  Say 'Setting up the voice: packages and models. The first time takes a few minutes.'
  powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir 'setup.ps1') | Out-Host
  if ($LASTEXITCODE -ne 0) { Fail 'Setup stopped (see above). Fix that and run this line again.'; Pop-Location; return }

  # 6. The window: Jarvis shows its words and buttons there.
  if ($env:JARVIS_NO_WINDOW -ne '1' -and -not (Test-Path (Join-Path $dir 'window\node_modules\electron\dist\electron.exe'))) {
    Say 'Installing the Jarvis window (about 250 MB)...'
    npm install --silent --prefix (Join-Path $dir 'window') | Out-Host
    node (Join-Path $dir 'window\node_modules\electron\install.js') | Out-Host
  }

  # The Start Menu shortcut, so Win+S finds "Jarvis".
  try { & (Join-Path $dir 'shortcut.ps1') } catch { Say 'No Start Menu shortcut (not needed to run Jarvis).' 'Yellow' }

  if ($env:JARVIS_NO_START -eq '1') {
    Pop-Location
    Say 'Jarvis is installed. Start it any time: tell Claude "start Jarvis from this folder".' 'Green'
    return
  }

  # 7. Start Jarvis in its own window, then the finish block. It is the last thing printed, and nothing runs after it.
  powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir 'start.ps1') -Quiet | Out-Null
  Pop-Location
  Write-Host ''
  Say 'Jarvis is installed.' 'Green'
  Write-Host ''
  Say 'Next, in the new Jarvis window:' 'White'
  Write-Host '     1. Pick "Yes, I trust this folder".'
  Write-Host '     2. Pick "I am using this for local development".'
  Write-Host '     3. If Claude Code asks you to log in, log in with your Claude account.'
  Write-Host '     4. Wait for Jarvis to greet you, then say "Hey Jarvis".'
  Write-Host ''
  Say "Later, just tell Claude: `"start Jarvis from $dir`" or `"uninstall Jarvis from $dir`"." 'DarkCyan'
  Write-Host ''
}
