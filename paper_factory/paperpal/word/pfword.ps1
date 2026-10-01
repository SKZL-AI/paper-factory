# PAPER FACTORY — Word/Paperpal driver asset (invoked from WSL via
# powershell.exe -File). Every verb prints ONE machine-parseable status line.
# No credentials are read or written; the existing Word/Paperpal login of the
# interactive session is used as-is (consultant brief H).
param(
    [Parameter(Mandatory=$true)][string]$Verb,
    [string]$Arg1 = "",
    [string]$Arg2 = ""
)
# pane text carries umlauts/em-dashes — emit UTF-8, not the legacy codepage
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}

function Out-Status($ok, $detail) {
    if ($ok) { Write-Output "PFWORD OK $detail" } else { Write-Output "PFWORD FAIL $detail" }
}

function Get-WordApp {
    try { return [Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application') }
    catch { return $null }
}

switch ($Verb) {
    'open' {
        # Arg1 = docx path (Windows form). Opens visible + maximized.
        try {
            $w = New-Object -ComObject Word.Application
            $w.Visible = $true
            $doc = $w.Documents.Open($Arg1)
            Start-Sleep -Seconds 2
            $w.WindowState = 1
            Start-Sleep -Seconds 1
            Out-Status $true "opened=$($doc.Name) pages=$($doc.ComputeStatistics(2))"
        } catch { Out-Status $false $_.Exception.Message }
    }
    'word-state' {
        $w = Get-WordApp
        if ($null -eq $w) { Out-Status $false 'no-word' ; break }
        $doc = $null
        try { $doc = $w.ActiveDocument } catch {}
        if ($null -eq $doc) { Out-Status $false 'no-active-document' ; break }
        Out-Status $true "doc=$($doc.Name) pages=$($doc.ComputeStatistics(2)) words=$($doc.ComputeStatistics(0))"
    }
    'saveas-copy' {
        # Arg1 = target path (Windows form). Saves A COPY; the open document
        # keeps editing the ORIGINAL (SaveAs2 with compatibility, then we do
        # not switch). We use SaveCopyAs semantics via Documents.Save + copy:
        $w = Get-WordApp
        if ($null -eq $w) { Out-Status $false 'no-word'; break }
        try {
            $doc = $w.ActiveDocument
            $doc.Save()   # persist the checked state of the open document
            Copy-Item -LiteralPath $doc.FullName -Destination $Arg1 -Force
            Out-Status $true "copy=$Arg1"
        } catch { Out-Status $false $_.Exception.Message }
    }
    'close' {
        $w = Get-WordApp
        if ($null -eq $w) { Out-Status $true 'already-closed'; break }
        try {
            foreach ($d in @($w.Documents)) { $d.Close([ref]$false) }
            $w.Quit()
            Out-Status $true 'closed'
        } catch { Out-Status $false $_.Exception.Message }
    }
    'shot' {
        # Arg1 = png path (Windows form)
        try {
            Add-Type -AssemblyName System.Windows.Forms, System.Drawing
            $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
            $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
            $bmp.Save($Arg1, [System.Drawing.Imaging.ImageFormat]::Png)
            Out-Status $true "shot=$($b.Width)x$($b.Height)"
        } catch { Out-Status $false $_.Exception.Message }
    }
    'click' {
        # Arg1 = x, Arg2 = y (virtual screen pixels)
        try {
            Add-Type -MemberDefinition '[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y); [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern void mouse_event(int f, int dx, int dy, int d, int e);' -Name U32 -Namespace W32PF
            [W32PF.U32]::SetCursorPos([int]$Arg1, [int]$Arg2) | Out-Null
            Start-Sleep -Milliseconds 250
            [W32PF.U32]::mouse_event(2, 0, 0, 0, 0)
            [W32PF.U32]::mouse_event(4, 0, 0, 0, 0)
            Out-Status $true "clicked=$Arg1,$Arg2"
        } catch { Out-Status $false $_.Exception.Message }
    }
    'uia-click' {
        # Arg1 = exact element name — InvokePattern ONLY, never the physical
        # mouse: the operator may be using the machine while we drive Word
        # (user requirement 2026-10-01). No InvokePattern → FAIL, and the
        # orchestrator falls back to bg-click (PostMessage, also cursor-free).
        try {
            Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
            $root = [System.Windows.Automation.AutomationElement]::RootElement
            $cls = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'OpusApp')
            $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cls)
            if ($null -eq $win) { Out-Status $false 'word-window-not-found'; break }
            $nm = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $Arg1)
            $els = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $nm)
            if ($els.Count -eq 0) { Out-Status $false "not-found:$Arg1"; break }
            $done = $false
            $tried = @()
            foreach ($el in $els) {
                $ct = $el.Current.ControlType.ProgrammaticName
                $tried += $ct
                try {
                    $ip = $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
                    $ip.Invoke()
                    Out-Status $true "invoked=$Arg1 ($ct)"
                    $done = $true
                    break
                } catch { }
            }
            if (-not $done) { Out-Status $false "no-invoke-pattern:$Arg1 on $($tried -join ',')" }
        } catch { Out-Status $false $_.Exception.Message }
    }
    'si-click' {
        # Arg1/Arg2 = screen pixels. SendInput (trusted-level synthetic
        # input) — WebView2/Chromium ignores plain PostMessage clicks; use
        # this for in-pane controls when UIA Invoke is unavailable.
        try {
            Add-Type -TypeDefinition @'
[System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
public struct PFINPUT { public uint type; public PFMOUSE mi; }
[System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
public struct PFMOUSE { public int dx, dy; public uint mouseData, dwFlags, time; public System.IntPtr dwExtraInfo; }
public static class PFSend {
  [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern uint SendInput(uint n, PFINPUT[] inputs, int cbSize);
  [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
}
'@
            Add-Type -AssemblyName System.Windows.Forms
            $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
            $ax = [int](([double]$Arg1 - $vs.Left) * 65535.0 / $vs.Width)
            $ay = [int](([double]$Arg2 - $vs.Top) * 65535.0 / $vs.Height)
            $move = New-Object PFINPUT
            $move.type = 0
            $move.mi = New-Object PFMOUSE
            $move.mi.dx = $ax
            $move.mi.dy = $ay
            $move.mi.dwFlags = 0x8001   # MOUSEEVENTF_ABSOLUTE | MOVE
            $down = New-Object PFINPUT
            $down.type = 0
            $down.mi = New-Object PFMOUSE
            $down.mi.dx = $ax
            $down.mi.dy = $ay
            $down.mi.dwFlags = 0x8002   # ABSOLUTE | LEFTDOWN
            $up = New-Object PFINPUT
            $up.type = 0
            $up.mi = New-Object PFMOUSE
            $up.mi.dx = $ax
            $up.mi.dy = $ay
            $up.mi.dwFlags = 0x8004   # ABSOLUTE | LEFTUP
            $sz = [System.Runtime.InteropServices.Marshal]::SizeOf((New-Object PFINPUT))
            $sent = [PFSend]::SendInput(3, [PFINPUT[]]@($move, $down, $up), $sz)
            if ($sent -eq 3) { Out-Status $true "si-clicked=$Arg1,$Arg2" } else { Out-Status $false "sendinput=$sent" }
        } catch { Out-Status $false $_.Exception.Message }
    }
    'bg-click' {
        # Arg1/Arg2 = virtual screen pixels. Posts WM_LBUTTONDOWN/UP to the
        # deepest Word child window under the point — the physical cursor
        # never moves and Word needs no focus (user requirement 2026-10-01).
        try {
            Add-Type -AssemblyName System.Drawing
            Add-Type -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string title);
  [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern IntPtr ChildWindowFromPoint(IntPtr parent, System.Drawing.Point pt);
  [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr h, ref System.Drawing.Point pt);
'@ -Name BgInput -Namespace PFInput -ReferencedAssemblies System.Drawing
            $hwnd = [PFInput.BgInput]::FindWindow('OpusApp', $null)
            if ($hwnd -eq [IntPtr]::Zero) { Out-Status $false 'word-window-not-found'; break }
            $pt = New-Object System.Drawing.Point([int]$Arg1, [int]$Arg2)
            $cur = $hwnd
            $cpt = $pt
            $depth = 0
            while ($depth -lt 12) {
                $tmp = $cpt
                [PFInput.BgInput]::ScreenToClient($cur, [ref]$tmp) | Out-Null
                $child = [PFInput.BgInput]::ChildWindowFromPoint($cur, $tmp)
                if ($child -eq [IntPtr]::Zero -or $child -eq $cur) { $cpt = $tmp; break }
                $cur = $child
                $cpt = $pt
                $depth++
            }
            $tmp = $pt
            [PFInput.BgInput]::ScreenToClient($cur, [ref]$tmp) | Out-Null
            $lp = [IntPtr](($tmp.Y -shl 16) -bor ($tmp.X -band 0xFFFF))
            [PFInput.BgInput]::PostMessage($cur, 0x0201, [IntPtr]1, $lp) | Out-Null
            [PFInput.BgInput]::PostMessage($cur, 0x0202, [IntPtr]0, $lp) | Out-Null
            Out-Status $true "bg-clicked=$($tmp.X),$($tmp.Y) hwnd=$cur"
        } catch { Out-Status $false $_.Exception.Message }
    }
    'shot-window' {
        # Arg1 = png path (Windows form). Captures ONLY the Word window via
        # PrintWindow — immune to other windows covering it (user requirement
        # 2026-10-01: the operator keeps working in the foreground).
        try {
            Add-Type -AssemblyName System.Drawing
            Add-Type -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string title);
  [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  public struct RECT { public int Left, Top, Right, Bottom; }
'@ -Name WinCap -Namespace PFCap -ReferencedAssemblies System.Drawing
            $hwnd = [PFCap.WinCap]::FindWindow('OpusApp', $null)
            if ($hwnd -eq [IntPtr]::Zero) { Out-Status $false 'word-window-not-found'; break }
            $r = New-Object "PFCap.WinCap+RECT"
            [PFCap.WinCap]::GetWindowRect($hwnd, [ref]$r) | Out-Null
            $wpx = $r.Right - $r.Left; $hpx = $r.Bottom - $r.Top
            $bmp = New-Object System.Drawing.Bitmap $wpx, $hpx
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            $dc = $g.GetHdc()
            [PFCap.WinCap]::PrintWindow($hwnd, $dc, 2) | Out-Null   # PW_RENDERFULLCONTENT
            $g.ReleaseHdc($dc)
            $bmp.Save($Arg1, [System.Drawing.Imaging.ImageFormat]::Png)
            Out-Status $true "wshot=$($wpx)x$($hpx)"
        } catch { Out-Status $false $_.Exception.Message }
    }
    'uia-dump-scope' {
        # Arg1 = ancestor element name, Arg2 = substring filter ('' = all).
        # Dumps the subtree UNDER that element (e.g. the Paperpal pane's
        # WebView2 content) — pixel-free pane verification.
        try {
            Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
            $root = [System.Windows.Automation.AutomationElement]::RootElement
            $cls = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'OpusApp')
            $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cls)
            if ($null -eq $win) { Out-Status $false 'word-window-not-found'; break }
            $nm = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $Arg1)
            $anchor = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $nm)
            if ($null -eq $anchor) { Out-Status $false "anchor-not-found:$Arg1"; break }
            $all = $anchor.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            $hits = @()
            foreach ($e in $all) {
                $n = $e.Current.Name
                if ($n -and $n.Trim().Length -gt 0 -and ($Arg2 -eq '' -or $n -like "*$Arg2*")) {
                    $hits += ($e.Current.ControlType.ProgrammaticName + '::' + $n)
                }
                if ($hits.Count -ge 300) { break }
            }
            Out-Status $true ("dump=" + ($hits -join ' || '))
        } catch { Out-Status $false $_.Exception.Message }
    }
    'uia-dump' {
        # Arg1 = substring filter ('' = all). Dumps text-bearing UIA elements
        # of the Word window subtree — pixel-free verification, works fully
        # unfocused/off-screen (user requirement 2026-10-01).
        try {
            Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
            $root = [System.Windows.Automation.AutomationElement]::RootElement
            $cls = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'OpusApp')
            $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cls)
            if ($null -eq $win) { Out-Status $false 'word-window-not-found'; break }
            $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            $hits = @()
            foreach ($e in $all) {
                $n = $e.Current.Name
                if ($n -and $n.Trim().Length -gt 0 -and ($Arg1 -eq '' -or $n -like "*$Arg1*")) {
                    $hits += ($e.Current.ControlType.ProgrammaticName + '::' + $n)
                }
                if ($hits.Count -ge 120) { break }
            }
            Out-Status $true ("dump=" + ($hits -join ' || '))
        } catch { Out-Status $false $_.Exception.Message }
    }
    'park' {
        # move Word off the visible screen — UIA/PostMessage keep working,
        # the operator's session is never disturbed (user req 2026-10-01)
        try {
            Add-Type -MemberDefinition '[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetWindowPos(System.IntPtr h, System.IntPtr after, int x, int y, int cx, int cy, uint flags); [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int c);' -Name Park -Namespace PFPark
            $p = Get-Process WINWORD -ErrorAction SilentlyContinue
            if ($null -eq $p) { Out-Status $false 'no-winword'; break }
            [PFPark.Park]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
            [PFPark.Park]::SetWindowPos($p.MainWindowHandle, [IntPtr]::Zero, 4000, 4000, 1900, 1080, 0x0040) | Out-Null
            Out-Status $true 'parked-offscreen'
        } catch { Out-Status $false $_.Exception.Message }
    }
    'unpark' {
        try {
            Add-Type -MemberDefinition '[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetWindowPos(System.IntPtr h, System.IntPtr after, int x, int y, int cx, int cy, uint flags); [System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int c);' -Name Park2 -Namespace PFPark2
            $p = Get-Process WINWORD -ErrorAction SilentlyContinue
            if ($null -eq $p) { Out-Status $false 'no-winword'; break }
            [PFPark2.Park2]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
            [PFPark2.Park2]::SetWindowPos($p.MainWindowHandle, [IntPtr]::Zero, 50, 50, 1900, 1000, 0x0040) | Out-Null
            Out-Status $true 'unparked'
        } catch { Out-Status $false $_.Exception.Message }
    }
    'uia-find' {
        # Arg1 = substring; lists matching UIA element names in Word window
        try {
            Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
            $root = [System.Windows.Automation.AutomationElement]::RootElement
            $cls = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ClassNameProperty, 'OpusApp')
            $win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cls)
            if ($null -eq $win) { Out-Status $false 'word-window-not-found'; break }
            $all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            $hits = @()
            foreach ($e in $all) {
                $n = $e.Current.Name
                if ($n -and $n -like "*$Arg1*") { $hits += $n }
                if ($hits.Count -ge 40) { break }
            }
            Out-Status $true ("matches=" + ($hits -join ' | '))
        } catch { Out-Status $false $_.Exception.Message }
    }
    default { Out-Status $false "unknown-verb:$Verb" }
}
