param([string]$ExePath = "", [string]$LaunchScript = "")

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ClearViewMouse {
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT point);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int command);
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
}
"@

function Get-Control($root, [string]$name, $controlType) {
    $nameCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::NameProperty, $name
    )
    $typeCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty, $controlType
    )
    return $root.FindFirst(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.AndCondition]::new($nameCondition, $typeCondition)
    )
}

function Click-Element($element) {
    if ($null -eq $element) { throw "Cannot click missing element" }
    $ready = $false
    for ($attempt = 0; $attempt -lt 10 -and -not $ready; $attempt++) {
        if ($script:mainWindowHandle -ne [IntPtr]::Zero) {
            [ClearViewMouse]::ShowWindowAsync($script:mainWindowHandle, 3) | Out-Null
            [ClearViewMouse]::SetForegroundWindow($script:mainWindowHandle) | Out-Null
            [System.Windows.Automation.AutomationElement]::FromHandle($script:mainWindowHandle).SetFocus()
        }
        if ($element.GetSupportedPatterns() -contains [System.Windows.Automation.ScrollItemPattern]::Pattern) {
            $element.GetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern).ScrollIntoView()
        }
        Start-Sleep -Milliseconds 250
        $bounds = $element.Current.BoundingRectangle
        $x = [int]($bounds.Left + $bounds.Width / 2)
        $y = [int]($bounds.Top + $bounds.Height / 2)
        [ClearViewMouse]::SetCursorPos($x, $y) | Out-Null
        Start-Sleep -Milliseconds 80
        $point = New-Object ClearViewMouse+POINT
        $point.X = $x
        $point.Y = $y
        $hit = [ClearViewMouse]::WindowFromPoint($point)
        $hitPid = [uint32]0
        [ClearViewMouse]::GetWindowThreadProcessId($hit, [ref]$hitPid) | Out-Null
        $foreground = [ClearViewMouse]::GetForegroundWindow()
        $cursor = [System.Windows.Forms.Cursor]::Position
        Write-Host "CLICK='$($element.Current.Name)' X=$x Y=$y CURSOR=$($cursor.X),$($cursor.Y) RECT=$($bounds.Left),$($bounds.Top),$($bounds.Width),$($bounds.Height) FOREGROUND=$foreground HIT_PID=$hitPid APP_PID=$($script:process.Id)"
        $ready = $hitPid -eq $script:process.Id -and $foreground.ToInt64() -eq $script:mainWindowHandle.ToInt64() -and $cursor.X -eq $x -and $cursor.Y -eq $y
        if (-not $ready) { Start-Sleep -Milliseconds 250 }
    }
    if (-not $ready) { throw "Click target is not owned by ClearView: $($element.Current.Name)" }
    [ClearViewMouse]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 60
    [ClearViewMouse]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Milliseconds 500
}

function Select-Tab($window, [string]$name) {
    $tab = Get-Control $window $name ([System.Windows.Automation.ControlType]::TabItem)
    if ($null -eq $tab) { throw "Tab not found: $name" }
    $tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
    Start-Sleep -Milliseconds 250
}

function Find-Bookmark($window) {
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ListItem
    )
    $items = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    for ($index = 0; $index -lt $items.Count; $index++) {
        $item = $items.Item($index)
        if ($item.Current.Name -match '^2\s' -and -not $item.Current.IsOffscreen) { return $item }
    }
    return $null
}

function Assert-ReadingPosition($window, [string]$page, [double]$minimumRatio, [double]$maximumRatio) {
    $editCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit
    )
    $edit = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $editCondition)
    $actualPage = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
    if ($actualPage -ne $page) { throw "Expected page $page, got $actualPage" }
    $scrollCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ScrollBar
    )
    $scroll = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $scrollCondition)
    $range = $scroll.GetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern).Current
    $ratio = ($range.Value - $range.Minimum) / ($range.Maximum - $range.Minimum)
    if ($ratio -lt $minimumRatio -or $ratio -gt $maximumRatio) {
        throw "Page $page scroll ratio $ratio outside $minimumRatio..$maximumRatio (value=$($range.Value), max=$($range.Maximum))"
    }
    Write-Host "PAGE=$page SCROLL_VALUE=$([int]$range.Value) MAX=$([int]$range.Maximum) RATIO=$([math]::Round($ratio, 3))"
}

$rootDir = Split-Path -Parent $PSScriptRoot
$exe = if ($ExePath) { $ExePath } else { Join-Path $rootDir "ClearViewPDF.exe" }
$verification = Join-Path $rootDir "verification"
New-Item -ItemType Directory -Force -Path $verification | Out-Null
$sample = Join-Path $verification ("navigation-smoke-{0}.pdf" -f [DateTime]::Now.ToString("yyyyMMdd-HHmmssfff"))
Copy-Item -Path (Join-Path $rootDir "samples\reading-demo.pdf") -Destination $sample
if ($LaunchScript) {
    $python = Join-Path $rootDir ".venv-win\Scripts\python.exe"
    $arguments = '"' + $LaunchScript + '" "' + $sample + '"'
    $process = Start-Process -FilePath $python -ArgumentList $arguments -PassThru
} else {
    $process = Start-Process -FilePath $exe -ArgumentList ('"' + $sample + '"') -PassThru
}
try {
    $window = $null
    $pageTwo = $null
    for ($attempt = 0; $attempt -lt 100 -and $null -eq $pageTwo; $attempt++) {
        Start-Sleep -Milliseconds 100
        $process.Refresh()
        if ($process.HasExited) { throw "Packaged process exited early: $($process.ExitCode)" }
        if ($process.MainWindowHandle -ne 0) {
            $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
            if ($null -ne $window) {
                $pageTwo = Get-Control $window "2" ([System.Windows.Automation.ControlType]::ListItem)
                if ($null -ne $pageTwo -and $pageTwo.Current.IsOffscreen) { $pageTwo = $null }
            }
        }
    }
    if ($null -eq $pageTwo) { throw "Page 2 thumbnail did not appear" }
    $script:mainWindowHandle = $process.MainWindowHandle

    Start-Sleep -Milliseconds 750
    [ClearViewMouse]::ShowWindowAsync($process.MainWindowHandle, 3) | Out-Null
    [ClearViewMouse]::SetForegroundWindow($process.MainWindowHandle) | Out-Null
    $window.SetFocus()
    Start-Sleep -Milliseconds 750
    Click-Element $pageTwo
    $selection = $pageTwo.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current
    Write-Host "THUMBNAIL2_SELECTED=$($selection.IsSelected) FOCUSED=$($pageTwo.Current.HasKeyboardFocus) OFFSCREEN=$($pageTwo.Current.IsOffscreen)"
    Assert-ReadingPosition $window "2" 0.25 0.65
    Write-Host "THUMBNAIL_REAL_MOUSE_NAVIGATION=OK"

    Select-Tab $window "Bookmarks"
    $prompt = $null
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ListItem
    )
    $items = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    for ($index = 0; $index -lt $items.Count; $index++) {
        if ($items.Item($index).Current.Name -like "No bookmarks*") { $prompt = $items.Item($index); break }
    }
    if ($null -eq $prompt) { throw "Empty-bookmarks action prompt not found" }
    Click-Element $prompt
    $bookmark = Find-Bookmark $window
    if ($null -eq $bookmark) { throw "Clicking empty-bookmarks prompt did not add page 2" }
    Write-Host "EMPTY_BOOKMARKS_ACTION=OK"

    Select-Tab $window "Pages"
    $pageOne = Get-Control $window "1" ([System.Windows.Automation.ControlType]::ListItem)
    Click-Element $pageOne
    $pageOneSelection = $pageOne.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current
    Write-Host "THUMBNAIL1_SELECTED=$($pageOneSelection.IsSelected) FOCUSED=$($pageOne.Current.HasKeyboardFocus) OFFSCREEN=$($pageOne.Current.IsOffscreen)"
    Assert-ReadingPosition $window "1" 0.0 0.10

    Select-Tab $window "Bookmarks"
    $bookmark = Find-Bookmark $window
    Click-Element $bookmark
    $bookmarkSelection = $bookmark.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current
    Write-Host "BOOKMARK_SELECTED=$($bookmarkSelection.IsSelected) FOCUSED=$($bookmark.Current.HasKeyboardFocus) OFFSCREEN=$($bookmark.Current.IsOffscreen)"
    Assert-ReadingPosition $window "2" 0.25 0.65
    Write-Host "BOOKMARK_REAL_MOUSE_NAVIGATION=OK"
    Write-Host "PACKAGED_NAVIGATION_SMOKE_OK=1"
} finally {
    if (-not $process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        Start-Sleep -Seconds 2
        if (-not $process.HasExited) { $process.Kill() }
    }
}
