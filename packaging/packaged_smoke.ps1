param([string]$ExePath = "")

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName Microsoft.VisualBasic

function Get-Control($root, [string]$name, $controlType) {
    $nameCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::NameProperty, $name
    )
    $typeCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty, $controlType
    )
    $condition = [System.Windows.Automation.AndCondition]::new($nameCondition, $typeCondition)
    return $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
}

function Invoke-Control($control) {
    if ($null -eq $control) { throw "Control not found" }
    $control.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
}

function Select-Tab($window, [string]$name) {
    $tab = Get-Control $window $name ([System.Windows.Automation.ControlType]::TabItem)
    if ($null -eq $tab) { throw "Tab not found: $name" }
    $pattern = $tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
    $pattern.Select()
    Start-Sleep -Milliseconds 300
    if (-not $pattern.Current.IsSelected) { throw "Tab did not select: $name" }
    Write-Host "TAB_SELECTED=$name"
}

function Read-Rotation([string]$statePath, [string]$documentPath) {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $property = $state.documents.PSObject.Properties | Where-Object Name -EQ $documentPath | Select-Object -First 1
    if ($null -eq $property) { throw "No saved state for $documentPath" }
    return [int]$property.Value.rotation
}

$rootDir = Split-Path -Parent $PSScriptRoot
$exe = if ($ExePath) { $ExePath } else { Join-Path $rootDir "ClearViewPDF.exe" }
$sample = Join-Path $rootDir "samples\semantic-smoke.pdf"
$statePath = Join-Path $env:APPDATA "ClearView\ClearView PDF\reading-state.json"
$process = Start-Process -FilePath $exe -ArgumentList ('"' + $sample + '"') -PassThru
try {
    Start-Sleep -Seconds 6
    $process.Refresh()
    if ($process.HasExited) { throw "Packaged process exited early: $($process.ExitCode)" }
    $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    if ($null -eq $window) { throw "No main window handle" }
    Write-Host "PACKAGED_EXE_RUNNING PID=$($process.Id)"
    Write-Host "WINDOW_TITLE=$($window.Current.Name)"
    if ($window.Current.Name -notlike "semantic-smoke.pdf*") { throw "Sample PDF did not open" }

    foreach ($name in @("Pages", "Contents", "Bookmarks")) {
        $tab = Get-Control $window $name ([System.Windows.Automation.ControlType]::TabItem)
        if ($null -eq $tab -or $tab.Current.IsOffscreen) { throw "Missing/offscreen tab: $name" }
    }
    foreach ($name in @("Bookmark", "Rotate CW", "Rotate CCW", "Reset")) {
        $button = Get-Control $window $name ([System.Windows.Automation.ControlType]::Button)
        if ($null -ne $button) { throw "Removed toolbar button is still present: $name" }
    }
    foreach ($name in @("File", "Edit", "View", "Go", "Help")) {
        $menu = Get-Control $window $name ([System.Windows.Automation.ControlType]::MenuItem)
        if ($null -eq $menu -or $menu.Current.IsOffscreen) { throw "Missing/offscreen menu: $name" }
    }
    Write-Host "MENUS_TABS_VISIBLE_AND_REMOVED_TOOLBAR_BUTTONS_ABSENT=1"

    Select-Tab $window "Contents"
    Select-Tab $window "Bookmarks"
    Select-Tab $window "Pages"

    [Microsoft.VisualBasic.Interaction]::AppActivate($process.Id)
    [System.Windows.Forms.SendKeys]::SendWait("^=")
    Start-Sleep -Seconds 1
    $rotation = Read-Rotation $statePath $sample
    if ($rotation -ne 90) { throw "Clockwise rotation shortcut did not persist: $rotation" }
    [System.Windows.Forms.SendKeys]::SendWait("^+=")
    Start-Sleep -Seconds 1
    $rotation = Read-Rotation $statePath $sample
    if ($rotation -ne 0) { throw "Counterclockwise rotation did not restore zero: $rotation" }
    Write-Host "ROTATION_ROUND_TRIP=90->0"

    Invoke-Control (Get-Control $window "Find" ([System.Windows.Automation.ControlType]::Button))
    Start-Sleep -Milliseconds 500
    $editCondition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit
    )
    $edits = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCondition)
    $searchEdit = $null
    for ($index = 0; $index -lt $edits.Count; $index++) {
        $candidate = $edits.Item($index)
        $value = $candidate.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        if ($value.Current.Value -eq "") { $searchEdit = $candidate }
    }
    if ($null -eq $searchEdit) { throw "Search edit not found" }
    $searchEdit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue("talks about GQA")
    $fuzzy = Get-Control $window "Fuzzy" ([System.Windows.Automation.ControlType]::CheckBox)
    if ($null -eq $fuzzy) { throw "Fuzzy checkbox not found" }
    $toggle = $fuzzy.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Off) {
        $toggle.Toggle()
    }
    $semantic = Get-Control $window "Semantic" ([System.Windows.Automation.ControlType]::CheckBox)
    if ($null -ne $semantic) { throw "Separate Semantic checkbox is still present" }

    $resultName = $null
    for ($attempt = 0; $attempt -lt 90 -and $null -eq $resultName; $attempt++) {
        Start-Sleep -Seconds 1
        $all = $window.FindAll(
            [System.Windows.Automation.TreeScope]::Descendants,
            [System.Windows.Automation.Condition]::TrueCondition
        )
        for ($index = 0; $index -lt $all.Count; $index++) {
            $current = $all.Item($index).Current
            if ($current.Name -eq "Semantic error") {
                throw "Packaged semantic search reported an error"
            }
            if ($current.ControlType -eq [System.Windows.Automation.ControlType]::ListItem -and $current.Name -match "\[semantic") {
                $resultName = $current.Name
                break
            }
        }
    }
    if ($null -eq $resultName) { throw "Timed out waiting for packaged semantic results" }
    Write-Host "PACKAGED_SEMANTIC_RESULT=$($resultName.Split("`n")[0])"
    [Microsoft.VisualBasic.Interaction]::AppActivate($process.Id)
    Start-Sleep -Milliseconds 300
    [System.Windows.Forms.SendKeys]::SendWait("^w")
    Start-Sleep -Seconds 1
    $process.Refresh()
    if ($process.HasExited) { throw "Ctrl+W quit the application instead of closing the document" }
    $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    if ($window.Current.Name -ne "ClearView PDF") {
        throw "Ctrl+W did not close the document: $($window.Current.Name)"
    }
    Write-Host "CTRL_W_CLOSE_DOCUMENT=OK"
    Write-Host "PACKAGED_UI_SMOKE_OK=1"
}
finally {
    if (-not $process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        Start-Sleep -Seconds 3
        if (-not $process.HasExited) { $process.Kill() }
    }
}
