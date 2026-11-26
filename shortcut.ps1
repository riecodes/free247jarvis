# The "Jarvis" Start Menu shortcut (per user), so Windows search finds it. install.ps1 adds it, uninstall.ps1 removes it.
#   shortcut.ps1 [-Port 8790]    make or refresh it (runs window\jarvis.vbs for this folder)
#   shortcut.ps1 -Remove         delete it, only if it belongs to this folder
# Keep this file ASCII: Windows PowerShell 5.1 runs it.
param([int]$Port = 0, [switch]$Remove)
$lnk = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Jarvis.lnk'
$vbs = Join-Path $PSScriptRoot 'window\jarvis.vbs'
$shell = New-Object -ComObject WScript.Shell
if ($Remove) {
  if ((Test-Path $lnk) -and $shell.CreateShortcut($lnk).Arguments -like "*$vbs*") { Remove-Item $lnk -Force }
  return
}
$s = $shell.CreateShortcut($lnk)
$s.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
$s.Arguments = "//B //Nologo `"$vbs`"" + $(if ($Port) { " $Port" })
$s.WorkingDirectory = $PSScriptRoot
$s.IconLocation = Join-Path $PSScriptRoot 'window\jarvis.ico'
$s.Description = 'Open Jarvis'
$s.Save()
