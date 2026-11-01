# A Windows notification from Jarvis, closed with its X, silent, for what must reach the user on screen. The text is in
# JARVIS_TOAST. voice.mjs starts one per toast. Windows PowerShell only: PowerShell 7 can't load these WinRT types.
$id = 'free247jarvis'
# How Windows knows the sender's name without an installed app. HKCU only.
$key = "HKCU:\Software\Classes\AppUserModelId\$id"
if (-not (Test-Path $key)) {
    New-Item $key -Force | Out-Null
    New-ItemProperty $key -Name DisplayName -Value 'Jarvis' | Out-Null
}
$null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime]
$text = [Security.SecurityElement]::Escape($env:JARVIS_TOAST)
$xml = [Windows.Data.Xml.Dom.XmlDocument]::new()
$xml.LoadXml("<toast duration='long'><visual><binding template='ToastGeneric'><text>$text</text></binding></visual><audio silent='true'/></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
# The same tag: a new one replaces the last instead of piling up.
$toast.Tag = 'voice'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show($toast)
