# Uninstalls freejarvis: stops Jarvis and deletes this folder. Safe to run again. Tell Claude "uninstall Jarvis from
# <this folder>" and it runs this file; Jarvis itself does the same when asked.
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1
# Keep this file ASCII: Windows PowerShell 5.1 runs it.
$dir = $PSScriptRoot
Set-Location $HOME   # a folder you stand in can't be deleted
$gem = [char]::ConvertFromUtf32(0x1F4A0)
function Say([string]$text, [string]$color = 'Cyan') { Write-Host "$gem $text" -ForegroundColor $color }

Say 'Stopping Jarvis...'
# Its own processes: anything started from this folder, and the voice server on its port (it starts as "node ../voice.mjs",
# so only the port owner whose parent chain reaches Jarvis's own Claude session counts: another app, or another
# Claude session's voice, may own that port and is left alone).
$port = if ($env:VOICE_PORT) { [int]$env:VOICE_PORT } else { 8790 }
$all = @(Get-CimInstance Win32_Process)
$jarvis = { param($p) $p.Name -match '^(claude|node)\.exe$' -and $p.CommandLine -match '--name jarvis\b' }
$mine = {
  param($p)
  for ($i = 0; $p -and $i -lt 8; $i++) { if (& $jarvis $p) { return $true }; $p = $all | Where-Object ProcessId -eq $p.ParentProcessId | Select-Object -First 1 }
  $false
}
$voice = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object OwningProcess |
  Where-Object { $id = $_; & $mine ($all | Where-Object ProcessId -eq $id | Select-Object -First 1) })
$all | Where-Object {
  (($_.Name -match '^(node|python|pythonw|electron)\.exe$' -and
    ((($_.ExecutablePath, $_.CommandLine) -join ' ') -like "*$dir*" -or $voice -contains $_.ProcessId)) -or
   # Jarvis's own Claude Code session (start.ps1 names it): it sits in the jarvis folder, which can't be deleted under it
   (& $jarvis $_))
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
