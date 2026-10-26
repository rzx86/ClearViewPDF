param([string]$SampleName = "semantic-smoke.pdf")

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$rootDir = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $rootDir "ClearViewPDF.exe"
$sample = Join-Path $rootDir "samples\$SampleName"
$process = Start-Process -FilePath $exe -ArgumentList ('"' + $sample + '"') -PassThru
try {
    Start-Sleep -Seconds 6
    $process.Refresh()
    if ($process.HasExited) { throw "Packaged process exited early: $($process.ExitCode)" }
    Write-Host "PACKAGED_EXE_RUNNING PID=$($process.Id)"
    $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    if ($null -eq $window) { throw "No main window handle" }
    Write-Host "WINDOW_TITLE=$($window.Current.Name)"
    $all = $window.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition
    )
    for ($index = 0; $index -lt $all.Count; $index++) {
        $current = $all.Item($index).Current
        if ($current.Name -or $current.ControlType.ProgrammaticName -match "Edit|CheckBox|TabItem|Button|ScrollBar") {
            Write-Host ("UI|{0}|{1}|offscreen={2}|enabled={3}" -f $current.ControlType.ProgrammaticName, $current.Name, $current.IsOffscreen, $current.IsEnabled)
        }
    }
}
finally {
    if (-not $process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        Start-Sleep -Seconds 2
        if (-not $process.HasExited) { $process.Kill() }
    }
}
