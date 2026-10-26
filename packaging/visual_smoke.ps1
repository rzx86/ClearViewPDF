param([string]$ExePath = "")

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ClearViewCaptureRect {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
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

function Get-WindowsDarkTheme {
    $settings = Get-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" -Name "AppsUseLightTheme"
    return ([int]$settings.AppsUseLightTheme -eq 0)
}

function Capture-Window($process, [string]$path) {
    $rect = New-Object ClearViewCaptureRect+RECT
    if (-not [ClearViewCaptureRect]::GetWindowRect($process.MainWindowHandle, [ref]$rect)) {
        throw "GetWindowRect failed"
    }
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    $bitmap = [System.Drawing.Bitmap]::new($width, $height)
    try {
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
        } finally {
            $graphics.Dispose()
        }
        $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $bitmap.Dispose()
    }
    return $rect
}

function Assert-MenuPixel([string]$path, $window, $rect, [int[]]$expected) {
    $help = Get-Control $window "Help" ([System.Windows.Automation.ControlType]::MenuItem)
    if ($null -eq $help) { throw "Help menu not found" }
    $bitmap = [System.Drawing.Bitmap]::FromFile($path)
    try {
        $x = $bitmap.Width - 20
        $y = [int](($help.Current.BoundingRectangle.Top + $help.Current.BoundingRectangle.Bottom) / 2 - $rect.Top)
        $pixel = $bitmap.GetPixel($x, $y)
        $actual = @($pixel.R, $pixel.G, $pixel.B)
        if (Compare-Object $actual $expected) {
            throw "Unexpected menu pixel at ${x},${y}: $actual expected $expected"
        }
        Write-Host "MENU_PIXEL=$($actual -join ',') EXPECTED=$($expected -join ',')"
    } finally {
        $bitmap.Dispose()
    }
}

function Assert-Document-White([string]$path) {
    $bitmap = [System.Drawing.Bitmap]::FromFile($path)
    try {
        $samples = 0
        for ($y = [int]($bitmap.Height * 0.20); $y -lt $bitmap.Height - 30; $y += 40) {
            for ($x = [int]($bitmap.Width * 0.35); $x -lt $bitmap.Width - 40; $x += 40) {
                $pixel = $bitmap.GetPixel($x, $y)
                if ($pixel.R -eq 255 -and $pixel.G -eq 255 -and $pixel.B -eq 255) { $samples++ }
            }
        }
        if ($samples -lt 20) { throw "Not enough unchanged white document samples found: $samples" }
        Write-Host "PDF_PAGE_WHITE_SAMPLES=$samples"
    } finally {
        $bitmap.Dispose()
    }
}

$rootDir = Split-Path -Parent $PSScriptRoot
$exe = if ($ExePath) { $ExePath } else { Join-Path $rootDir "ClearViewPDF.exe" }
$sample = Join-Path $rootDir "samples\semantic-smoke.pdf"
$outputDir = Join-Path $rootDir "verification"
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$capturePath = Join-Path $outputDir "clearview-system-theme.png"
$window = $null
$process = Start-Process -FilePath $exe -ArgumentList ('"' + $sample + '"') -PassThru
try {
    Start-Sleep -Seconds 6
    $process.Refresh()
    if ($process.HasExited) { throw "Packaged process exited early: $($process.ExitCode)" }
    $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    if ($null -eq $window) { throw "No main window handle" }
    $night = Get-Control $window "Night" ([System.Windows.Automation.ControlType]::CheckBox)
    if ($null -ne $night) { throw "Manual Night control should not exist" }
    $dark = Get-WindowsDarkTheme
    Write-Host "WINDOWS_DARK_THEME=$dark"

    $pages = Get-Control $window "Pages" ([System.Windows.Automation.ControlType]::TabItem)
    $pages.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
    Start-Sleep -Seconds 1
    $thumbnail = Get-Control $window "1" ([System.Windows.Automation.ControlType]::ListItem)
    if ($null -eq $thumbnail) { throw "Page 1 thumbnail not found" }
    $bounds = $thumbnail.Current.BoundingRectangle
    if ($bounds.Width -lt 180 -or $bounds.Height -lt 240) {
        throw "Thumbnail still too small: $($bounds.Width)x$($bounds.Height)"
    }
    Write-Host "THUMBNAIL_BOUNDS=$([int]$bounds.Width)x$([int]$bounds.Height)"

    $compactButtons = @()
    foreach ($name in @("First", "Prev", "Next", "Last", "Zoom out", "Zoom in")) {
        $button = Get-Control $window $name ([System.Windows.Automation.ControlType]::Button)
        if ($null -eq $button -or $button.Current.IsOffscreen) { throw "Missing/offscreen compact button: $name" }
        $compactButtons += $button
    }
    foreach ($name in @("Fit to width", "Fit to height")) {
        $button = Get-Control $window $name ([System.Windows.Automation.ControlType]::CheckBox)
        if ($null -eq $button) { $button = Get-Control $window $name ([System.Windows.Automation.ControlType]::Button) }
        if ($null -eq $button -or $button.Current.IsOffscreen) { throw "Missing/offscreen compact fit control: $name" }
        $compactButtons += $button
    }
    foreach ($name in @("Bookmark", "Rotate CW", "Rotate CCW", "Reset")) {
        $button = Get-Control $window $name ([System.Windows.Automation.ControlType]::Button)
        if ($null -ne $button) { throw "Removed toolbar button is still present: $name" }
    }
    $maxWidth = 0
    $maxHeight = 0
    foreach ($button in $compactButtons) {
        $bounds = $button.Current.BoundingRectangle
        $maxWidth = [Math]::Max($maxWidth, [int]$bounds.Width)
        $maxHeight = [Math]::Max($maxHeight, [int]$bounds.Height)
        if ($bounds.Width -gt 44 -or $bounds.Height -gt 38) {
            throw "Reading control is not compact: $($button.Current.Name) $($bounds.Width)x$($bounds.Height)"
        }
    }
    Write-Host "COMPACT_CONTROLS=$($compactButtons.Count) MAX_BOUNDS=${maxWidth}x${maxHeight}"

    $rect = Capture-Window $process $capturePath
    $expectedMenu = if ($dark) { @(37, 40, 44) } else { @(244, 245, 247) }
    Assert-MenuPixel $capturePath $window $rect $expectedMenu
    Assert-Document-White $capturePath
    Write-Host "SYSTEM_THEME_SCREENSHOT=$capturePath"
    Write-Host "PACKAGED_VISUAL_SMOKE_OK=1"
} finally {
    if (-not $process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        Start-Sleep -Seconds 2
        if (-not $process.HasExited) { $process.Kill() }
    }
}
