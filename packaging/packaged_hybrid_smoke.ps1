param([string]$ExePath = "")

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

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

function Enable-CheckBox($window, [string]$name) {
    $checkbox = Get-Control $window $name ([System.Windows.Automation.ControlType]::CheckBox)
    if ($null -eq $checkbox) { throw "Checkbox not found: $name" }
    $toggle = $checkbox.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
    if ($toggle.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::Off) {
        $toggle.Toggle()
    }
    Start-Sleep -Milliseconds 300
}

$rootDir = Split-Path -Parent $PSScriptRoot
$exe = if ($ExePath) { $ExePath } else { Join-Path $rootDir "ClearViewPDF.exe" }
$sample = Join-Path $rootDir "samples\hybrid-smoke.pdf"
$process = Start-Process -FilePath $exe -ArgumentList ('"' + $sample + '"') -PassThru
try {
    Start-Sleep -Seconds 6
    $process.Refresh()
    if ($process.HasExited) { throw "Packaged process exited early: $($process.ExitCode)" }
    $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    if ($null -eq $window -or $window.Current.Name -notlike "hybrid-smoke.pdf*") {
        throw "Hybrid sample did not open"
    }

    $find = Get-Control $window "Find" ([System.Windows.Automation.ControlType]::Button)
    $find.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
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
    $searchEdit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue("Serchable")
    Enable-CheckBox $window "Fuzzy"
    $semantic = Get-Control $window "Semantic" ([System.Windows.Automation.ControlType]::CheckBox)
    if ($null -ne $semantic) { throw "Separate Semantic checkbox is still present" }

    $resultNames = $null
    for ($attempt = 0; $attempt -lt 90 -and $null -eq $resultNames; $attempt++) {
        Start-Sleep -Seconds 1
        $process.Refresh()
        if ($process.HasExited) { throw "Packaged process exited during hybrid search: $($process.ExitCode)" }
        try {
            $all = $window.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition
            )
            $names = @()
            foreach ($element in $all) {
                $current = $element.Current
                if ($current.Name -eq "Semantic error") { throw "Packaged hybrid search reported an error" }
                if (
                    -not $current.IsOffscreen -and
                    $current.ControlType -eq [System.Windows.Automation.ControlType]::ListItem -and
                    $current.Name -match '^\d+\. Page '
                ) {
                    $names += $current.Name
                }
            }
        } catch [System.Runtime.InteropServices.COMException] {
            Start-Sleep -Milliseconds 250
            continue
        }
        $hasText = $names | Where-Object { $_ -match '^1\. Page 1' -and $_ -notmatch '\[semantic' }
        $hasSemantic = $names | Where-Object { $_ -match '^2\. Page 2\s+\[semantic\]' }
        if ($hasText -and $hasSemantic) {
            if ($names.Count -ne 2) { throw "Hybrid search returned duplicates: $($names -join ' | ')" }
            $resultNames = $names
        }
    }
    if ($null -eq $resultNames) { throw "Timed out waiting for combined fuzzy and semantic results" }
    foreach ($name in $resultNames) { Write-Host "HYBRID_RESULT=$($name.Split("`n")[0])" }
    Write-Host "PACKAGED_HYBRID_SMOKE_OK=1"
} finally {
    if (-not $process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        Start-Sleep -Seconds 3
        if (-not $process.HasExited) { $process.Kill() }
    }
}
