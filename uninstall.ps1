# Uninstalls freejarvis: stops Jarvis and deletes this folder. Safe to run again.
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1
# Keep this file ASCII: Windows PowerShell 5.1 runs it.
$dir = $PSScriptRoot
Set-Location $HOME   # a folder you stand in can't be deleted
$gem = [char]::ConvertFromUtf32(0x1F4A0)
function Say([string]$text, [string]$color = 'Cyan') { Write-Host "$gem $text" -ForegroundColor $color }

Say 'Stopping Jarvis...'
# Its own processes: anything started from this folder, and the voice server on its port (it starts as "node ../voice.mjs").
$port = if ($env:VOICE_PORT) { [int]$env:VOICE_PORT } else { 8790 }
$voice = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object OwningProcess)
Get-CimInstance Win32_Process | Where-Object {
  $_.Name -match '^(node|python|pythonw|electron)\.exe$' -and
  ((($_.ExecutablePath, $_.CommandLine) -join ' ') -like "*$dir*" -or $voice -contains $_.ProcessId)
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

Say "Deleting $dir ..."
Remove-Item -Recurse -Force $dir -ErrorAction SilentlyContinue
if (Test-Path $dir) {
  Write-Host "$gem Some files are still in use. Close the Jarvis window, then run this again." -ForegroundColor Yellow
} else {
  Write-Host ''
  Say 'Jarvis is uninstalled.' 'Green'
  Write-Host '     Git, Python, Node.js, Windows Terminal and Claude Code stay installed: you may use them for other things.'
  Write-Host '     Claude Code keeps its saved chats in your .claude folder.'
  Write-Host ''
}
