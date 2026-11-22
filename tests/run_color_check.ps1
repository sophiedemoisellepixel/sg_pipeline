# Checks that Maya, Nuke, Katana and Mari all use the pipeline's colour config
# (config/color/sg_pipeline.ocio) when OCIO is set the way the desktop app's
# before_app_launch hook sets it. Each application runs headless; no ShotGrid.
#
#   powershell -File tests\run_color_check.ps1

param(
    [string]$Maya = "C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe",
    [string]$Nuke = "C:\Program Files\Nuke17.1v3\Nuke17.1.exe",
    [string]$Katana = "C:\Program Files\Katana9.0v4\bin\katanaBin.exe",
    [string]$Mari = "C:\Program Files\Mari7.1v2\Bundle\bin\Mari7.1v2.exe",
    [int]$TimeoutSeconds = 300
)

$repo = Split-Path -Parent $PSScriptRoot
$env:OCIO = Join-Path $repo "config\color\sg_pipeline.ocio"
# what before_app_launch.py adds for Nuke
$env:NUKE_PATH = (@((Join-Path $repo "config\color\nuke")) + @($env:NUKE_PATH | Where-Object { $_ })) -join ";"
$script = Join-Path $PSScriptRoot "color_config_check.py"
$failures = @()

function Invoke-Check([string]$label, [string]$exe, [string[]]$arguments) {
    $out = Join-Path $env:TEMP "sg_pipeline_color_$label.txt"
    $p = Start-Process -FilePath $exe -ArgumentList $arguments -RedirectStandardOutput $out -RedirectStandardError "$out.err" -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit($TimeoutSeconds * 1000)) { Stop-Process -Id $p.Id -Force -Confirm:$false }
    $line = Get-Content $out -ErrorAction SilentlyContinue | Where-Object { $_ -like "RESULT *" } | Select-Object -Last 1
    if (-not $line) { return @{ host = $label; error = "no result" } }
    return ($line.Substring(7) | ConvertFrom-Json)
}

$results = [ordered]@{
    maya   = Invoke-Check "maya" $Maya @("`"$script`"")
    nuke   = Invoke-Check "nuke" $Nuke @("-t", "-i", "`"$script`"")
    katana = Invoke-Check "katana" $Katana @("--script", "`"$script`"")
    mari   = Invoke-Check "mari" $Mari @("-x", "`"$script`"")
}

foreach ($name in $results.Keys) {
    $r = $results[$name]
    $ok = (-not $r.error) -and ($r.config_name -eq "sg_pipeline") -and ($r.png -eq "sRGB - Texture") -and ($r.exr -eq "ACEScg")
    # the application itself, not only its OCIO library, must use the config
    if ($name -eq "maya") { $ok = $ok -and $r.cm_enabled -and ($r.maya_png_file_node -eq "sRGB - Texture") }
    if ($name -eq "nuke") { $ok = $ok -and ($r.color_management -eq "OCIO") -and ($r.ocio_config_knob -eq "custom") }
    "{0}  {1}: config '{2}' (OCIO {3}), png -> {4}, exr -> {5}, scene_linear {6}" -f ($(if ($ok) { "PASS" } else { "FAIL" })), $name, $r.config_name, $r.ocio_version, $r.png, $r.exr, $r.scene_linear
    if ($name -eq "maya" -and $r.cm_enabled -ne $null) { "      Maya: colour management on = $($r.cm_enabled), config = $($r.config_path), rendering space = $($r.rendering_space), new PNG file node = $($r.maya_png_file_node)" }
    if ($name -eq "nuke" -and $r.color_management) { "      Nuke: $($r.color_management), OCIO_config = $($r.ocio_config_knob), working space = $($r.working_space), PNG Read = $($r.nuke_png_read)" }
    if ($r.error) { "      error: $($r.error)" }
    if (-not $ok) { $failures += $name }
}
if ($failures) { "`n$($failures.Count) FAILED: $($failures -join ', ')"; exit 1 } else { "`nALL CHECKS PASSED" }
