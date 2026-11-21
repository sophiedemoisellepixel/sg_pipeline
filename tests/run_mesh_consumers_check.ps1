# Checks that Substance 3D Painter and Mari can each build a project from a USD
# file, without ShotGrid: use it on what griptape/mesh_to_usd.py wrote. Painter
# opens a window and is stopped after the timeout if it does not close itself;
# Mari runs headless.
#
#   powershell -File tests\run_mesh_consumers_check.ps1 -Usd <file.usd>

param(
    [Parameter(Mandatory = $true)][string]$Usd,
    [int]$TimeoutSeconds = 300,
    # the version the pipeline launches; Mari 8.0v1 exits without running -x scripts here
    [string]$MariExe = "C:\Program Files\Mari7.1v2\Bundle\bin\Mari7.1v2.exe"
)

$repo = Split-Path -Parent $PSScriptRoot
$Usd = (Resolve-Path $Usd).Path
$env:SG_PIPELINE_MESH_CHECK_USD = $Usd
$results = [ordered]@{}

function Wait-Exit($process, [string]$label) {
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $process.Id -Force -Confirm:$false
        "note: $label (pid $($process.Id)) did not exit within $TimeoutSeconds s and was stopped."
    }
}

# ---- Painter
$out = Join-Path $env:TEMP "sg_pipeline_mesh_check_painter.json"
Remove-Item $out -ErrorAction SilentlyContinue
$env:SG_PIPELINE_MESH_CHECK_OUT = $out
$env:SUBSTANCE_PAINTER_PLUGINS_PATH = "$repo\tests\mesh_consumers\painter"
$painter = "C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe"
Wait-Exit (Start-Process -FilePath $painter -PassThru) "Painter"
$results.painter = if (Test-Path $out) { Get-Content $out -Raw | ConvertFrom-Json } else { "no result" }

# ---- Mari
$out = Join-Path $env:TEMP "sg_pipeline_mesh_check_mari.json"
Remove-Item $out -ErrorAction SilentlyContinue
$env:SG_PIPELINE_MESH_CHECK_OUT = $out
Wait-Exit (Start-Process -FilePath $MariExe -ArgumentList "-x", "`"$repo\tests\mesh_consumers\mari_mesh_check.py`"" -PassThru -WindowStyle Hidden) "Mari"
$results.mari = if (Test-Path $out) { Get-Content $out -Raw | ConvertFrom-Json } else { "no result" }

$results | ConvertTo-Json -Depth 6
