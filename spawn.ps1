# Opens Claude Code worker terminals named after their grid cell: t1 to t6 in a 3x2 grid, numbered in
# reading order (t1 top left, t3 top right, t4 bottom left). The grid is 3 columns over 92% of the screen
# width, centered, so strips stay free on both sides. A number is free while no Terminal window is titled
# with it (Claude Code titles the window with the session name); other windows are ignored, so a worker
# can cover them.
#   spawn.ps1 [-Count 1] [-Dir folder]   open workers in the lowest free cells, by default in the folder
#                                        that holds free247jarvis
#   spawn.ps1 -List                      print each worker window and the cell it sits in
param([int]$Count = 1, [string]$Dir = (Split-Path $PSScriptRoot), [switch]$List)

$Cols = 3; $Rows = 2; $Width = 0.92

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class Cells {
    struct RECT { public int L, T, R, B; }
    struct MONITORINFO { public int cbSize; public RECT rcMonitor, rcWork; public int dwFlags; }
    delegate bool EnumProc(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr p);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int hgt, uint flags);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] static extern IntPtr MonitorFromWindow(IntPtr h, uint flags);
    [DllImport("user32.dll")] static extern bool GetMonitorInfo(IntPtr m, ref MONITORINFO mi);
    [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr ctx);
    [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr h, int attr, out RECT r, int size);
    [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int v, int size);

    // Every Windows Terminal window, minimized or not: a minimized worker still holds its name.
    public static IntPtr[] Terminals() {
        var l = new List<IntPtr>();
        EnumWindows((h, p) => {
            var s = new StringBuilder(64); GetClassName(h, s, 64);
            if (IsWindowVisible(h) && s.ToString() == "CASCADIA_HOSTING_WINDOW_CLASS") l.Add(h);
            return true;
        }, IntPtr.Zero);
        return l.ToArray();
    }

    public static string Title(IntPtr h) { var s = new StringBuilder(256); GetWindowText(h, s, 256); return s.ToString(); }

    // Per-monitor v2 for the call, so all numbers are physical pixels.
    static IntPtr dpiOld;
    static void Dpi() { dpiOld = SetThreadDpiAwarenessContext((IntPtr)(-4)); }
    static void Undpi() { SetThreadDpiAwarenessContext(dpiOld); }

    // Visible frame, without the invisible resize borders GetWindowRect includes.
    static RECT Frame(IntPtr h) { RECT r; if (DwmGetWindowAttribute(h, 9, out r, 16) != 0) GetWindowRect(h, out r); return r; }
    static RECT Work(IntPtr h) {
        var mi = new MONITORINFO { cbSize = Marshal.SizeOf(typeof(MONITORINFO)) };
        GetMonitorInfo(MonitorFromWindow(h, 2), ref mi);
        return mi.rcWork;
    }

    // Cell under the window's center (0 = top left, reading order), -1 when outside the grid.
    public static int CellOf(IntPtr h, int cols, int rows, double widthFrac) {
        Dpi();
        try {
            RECT wa = Work(h), f = Frame(h);
            int w = (int)((wa.R - wa.L) * widthFrac) / cols, ht = (wa.B - wa.T) / rows;
            int x = wa.L + (wa.R - wa.L - w * cols) / 2, y = wa.T;
            int cx = (f.L + f.R) / 2 - x, cy = (f.T + f.B) / 2 - y;
            return cx < 0 || cy < 0 || cx >= w * cols || cy >= ht * rows ? -1 : cy / ht * cols + cx / w;
        } finally { Undpi(); }
    }

    public static void Place(IntPtr h, int cell, int cols, int rows, double widthFrac) {
        Dpi();
        try {
            ShowWindow(h, 9); // restore, in case it opened maximized
            RECT wa = Work(h), wr, fr = Frame(h);
            GetWindowRect(h, out wr);
            int w = (int)((wa.R - wa.L) * widthFrac) / cols, ht = (wa.B - wa.T) / rows;
            int px = wa.L + (wa.R - wa.L - w * cols) / 2 + cell % cols * w, py = wa.T + cell / cols * ht;
            SetWindowPos(h, IntPtr.Zero, px - (fr.L - wr.L), py - (fr.T - wr.T),
                w + (fr.L - wr.L) + (wr.R - fr.R), ht + (fr.T - wr.T) + (wr.B - fr.B), 0x14); // NOZORDER | NOACTIVATE
            int square = 1; DwmSetWindowAttribute(h, 33, ref square, 4); // square corners, like a snapped window
        } finally { Undpi(); }
    }
}
'@

# Claude Code titles the window "<status> t2"; the status character changes while it works.
function Workers {
    foreach ($h in [Cells]::Terminals()) {
        if ([Cells]::Title($h) -match '(^|\s)t([1-9])$') { [pscustomobject]@{ Name = "t$($Matches[2])"; Window = $h } }
    }
}

if ($List) {
    foreach ($w in Workers) { "$($w.Name) cell $([Cells]::CellOf($w.Window, $Cols, $Rows, $Width) + 1)" }
    exit
}

if (-not (Test-Path -LiteralPath $Dir -PathType Container)) { "No such folder: $Dir"; exit 1 }
$Dir = (Resolve-Path -LiteralPath $Dir).Path
# A worker in the boss folder would load the voice channel too and fight the boss for the microphone.
if (Test-Path -LiteralPath (Join-Path $Dir '.mcp.json')) {
    if ((Get-Content -Raw -LiteralPath (Join-Path $Dir '.mcp.json')) -match 'voice\.mjs') { "Not in the boss folder: $Dir"; exit 1 }
}

# wt.exe hands the caller's environment to the new window. Claude Code sets NO_COLOR and CLAUDE* for its
# tool shells, which would start a colorless child of the boss session.
Get-ChildItem env: | Where-Object Name -match '^(CLAUDE|NO_COLOR$|GIT_TERMINAL_PROMPT$)' | ForEach-Object { Remove-Item "env:$($_.Name)" }

$opened = @()
for ($i = 0; $i -lt $Count; $i++) {
    $taken = @(Workers | ForEach-Object Name) + $opened
    $n = 1..($Cols * $Rows) | Where-Object { "t$_" -notin $taken } | Select-Object -First 1
    if (-not $n) { "All $($Cols * $Rows) terminals are already open."; exit 1 }
    $before = [Cells]::Terminals()
    Start-Process wt.exe -ArgumentList '-w', 'new', '-d', "`"$Dir`"", 'claude', '--name', "t$n", '--dangerously-skip-permissions'
    # Wait for the new window, then move it into its cell before the next one picks a number.
    $new = $null
    for ($t = 0; $t -lt 100 -and -not $new; $t++) {
        Start-Sleep -Milliseconds 150
        $new = [Cells]::Terminals() | Where-Object { $_ -notin $before } | Select-Object -First 1
    }
    if (-not $new) { "Terminal t$n did not open."; exit 1 }
    [Cells]::Place($new, $n - 1, $Cols, $Rows, $Width)
    $opened += "t$n"
    "Opened terminal $n (session t$n) in $Dir."
}
