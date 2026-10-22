# Windows GUI control for the boss. Claude Code's computer use runs only on macOS in the CLI, so on Windows
# the boss looks with screenshots and acts with these commands:
#   gui.ps1 shot [file]         screenshot of the whole screen (default tmp\screen.png), physical pixels
#   gui.ps1 windows             visible windows: handle, process, title
#   gui.ps1 open <app> [args]   start an app and bring its new window to the front
#   gui.ps1 focus <title>       bring the first window whose title contains <title> to the front
#   gui.ps1 type <text>         type text into the window in front
#   gui.ps1 keys <keys>         send keys in SendKeys notation: ^n (Ctrl+N), {ENTER}, %{F4} (Alt+F4)
#   gui.ps1 click <x> <y>       left click at screenshot coordinates
param([Parameter(Mandatory)][string]$Command, [Parameter(ValueFromRemainingArguments)][string[]]$Rest)

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class Gui {
    delegate bool EnumProc(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr GetWindow(IntPtr h, uint cmd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll")] static extern void mouse_event(uint flags, int x, int y, uint data, UIntPtr extra);

    public static void DpiAware() { SetProcessDPIAware(); }
    public static string Title(IntPtr h) { var s = new StringBuilder(512); GetWindowText(h, s, 512); return s.ToString(); }
    // Top-level windows with a title, front to back.
    public static IntPtr[] Windows() {
        var l = new List<IntPtr>();
        EnumWindows((h, p) => { if (IsWindowVisible(h) && GetWindow(h, 4) == IntPtr.Zero && Title(h).Length > 0) l.Add(h); return true; }, IntPtr.Zero);
        return l.ToArray();
    }
    // Windows lets only the foreground app hand out focus, so borrow the foreground thread's input for a moment.
    public static bool Front(IntPtr h) {
        if (IsIconic(h)) ShowWindow(h, 9);
        uint pid, fg = GetWindowThreadProcessId(GetForegroundWindow(), out pid), me = GetCurrentThreadId();
        keybd_event(0x12, 0, 0, UIntPtr.Zero); keybd_event(0x12, 0, 2, UIntPtr.Zero); // an Alt tap unlocks SetForegroundWindow
        AttachThreadInput(me, fg, true);
        SetForegroundWindow(h); BringWindowToTop(h);
        AttachThreadInput(me, fg, false);
        return GetForegroundWindow() == h;
    }
    public static void Click(int x, int y) { SetCursorPos(x, y); mouse_event(2, 0, 0, 0, UIntPtr.Zero); mouse_event(4, 0, 0, 0, UIntPtr.Zero); }
}
'@
[Gui]::DpiAware()

function Find([string]$Title) { [Gui]::Windows() | Where-Object { [Gui]::Title($_) -like "*$Title*" } | Select-Object -First 1 }
# SendKeys treats + ^ % ~ ( ) { } [ ] as commands; braces make them literal.
function Literal([string]$Text) { [regex]::Replace($Text, '[+^%~(){}\[\]]', '{$0}') -replace "`r?`n", '{ENTER}' }

$text = $Rest -join ' '
switch ($Command) {
    'shot' {
        $file = if ($text) { $text } else { Join-Path $PSScriptRoot 'tmp\screen.png' }
        $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
        $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
        [System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
        New-Item -ItemType Directory -Force (Split-Path $file) | Out-Null
        $bmp.Save($file)
        "$file ($($b.Width)x$($b.Height); click takes these pixel coordinates)"
    }
    'windows' {
        foreach ($h in [Gui]::Windows()) {
            $id = 0; [Gui]::GetWindowThreadProcessId($h, [ref]$id) | Out-Null
            "$h  $((Get-Process -Id $id -ErrorAction SilentlyContinue).ProcessName)  $([Gui]::Title($h))"
        }
    }
    'open' {
        $before = [Gui]::Windows()
        # A bare name like notepad goes to its .exe: Git Bash puts an extensionless notepad script first on
        # PATH, which Windows would offer to open with some app instead.
        $app = $Rest[0]
        if ($app -notmatch '[\\/:.]') {
            $exe = Get-Command "$app.exe" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($exe) { $app = $exe.Source }
        }
        if ($Rest.Count -gt 1) { Start-Process $app -ArgumentList $Rest[1..($Rest.Count - 1)] } else { Start-Process $app }
        $new = $null
        for ($t = 0; $t -lt 50 -and -not $new; $t++) {
            Start-Sleep -Milliseconds 200
            $new = [Gui]::Windows() | Where-Object { $_ -notin $before } | Select-Object -First 1
        }
        # Some apps (Notepad on Windows 11) reuse a window that is already open instead of making a new one.
        if (-not $new) { $new = Find $Rest[0] }
        if (-not $new) { "Started $($Rest[0]), but no window showed up."; exit 1 }
        if (-not [Gui]::Front($new)) { "Started, but could not bring $([Gui]::Title($new)) to the front."; exit 1 }
        Start-Sleep -Milliseconds 500
        "In front: $([Gui]::Title($new))"
    }
    'focus' {
        $h = Find $text
        if (-not $h) { "No window titled like '$text'."; exit 1 }
        if (-not [Gui]::Front($h)) { "Could not bring $([Gui]::Title($h)) to the front."; exit 1 }
        Start-Sleep -Milliseconds 300
        "In front: $([Gui]::Title($h))"
    }
    'type' { [System.Windows.Forms.SendKeys]::SendWait((Literal $text)); "Typed." }
    'keys' { [System.Windows.Forms.SendKeys]::SendWait($text); "Sent." }
    'click' { [Gui]::Click([int]$Rest[0], [int]$Rest[1]); "Clicked $($Rest[0]),$($Rest[1])." }
    default { "Unknown command: $Command"; exit 1 }
}
