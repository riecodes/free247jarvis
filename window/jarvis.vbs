' Opens Jarvis: brings the window up if the voice is running, otherwise starts Jarvis (start.ps1). No console window.
' The Start Menu shortcut "Jarvis" runs this; the first argument is the voice port (default VOICE_PORT in .env, else 8790).
Dim fso, sh, dir, port, ts, m, ok
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
port = "8790"
If fso.FileExists(dir & "\.env") Then
  Set ts = fso.OpenTextFile(dir & "\.env", 1)
  Do Until ts.AtEndOfStream
    m = Trim(ts.ReadLine())
    If LCase(Left(m, 11)) = "voice_port=" And Len(m) > 11 Then port = Trim(Mid(m, 12))
  Loop
  ts.Close
End If
If WScript.Arguments.Count > 0 Then port = WScript.Arguments(0)
ok = False
On Error Resume Next
With CreateObject("MSXML2.ServerXMLHTTP.6.0")
  .setTimeouts 1000, 1000, 2000, 3000
  .open "POST", "http://127.0.0.1:" & port & "/window", False
  .send
  ok = (Err.Number = 0)  ' any answer means the voice is up
End With
On Error GoTo 0
If Not ok Then sh.Run "powershell -NoProfile -ExecutionPolicy Bypass -File """ & dir & "\start.ps1"" -Quiet", 0, False
