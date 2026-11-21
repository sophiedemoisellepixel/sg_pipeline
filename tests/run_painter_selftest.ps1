# Starts a NEW Substance 3D Painter window with the Toolkit engine, lets the
# self-test plugin create a project from the newest USD Geometry publish, then
# Painter closes itself and the result is printed. Only reads from ShotGrid,
# unless -Publish is given, which registers the exported textures as publishes.
#
#   powershell -File tests\run_painter_selftest.ps1 [-EntityType Project] [-EntityId 91]

param(
    [string]$EntityType = "Project",
    [int]$EntityId = 91,
    [int]$TimeoutSeconds = 300,
    # WRITES to ShotGrid: registers the exported textures as publishes
    [switch]$Publish
)
$env:SG_PIPELINE_SELFTEST_PUBLISH = if ($Publish) { "1" } else { "0" }

$repo = Split-Path -Parent $PSScriptRoot
$cache = "C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
$painter = "C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe"
$out = Join-Path $env:TEMP "sg_pipeline_painter_selftest.json"
Remove-Item $out -ErrorAction SilentlyContinue

$env:TK_BOOTSTRAP_CONFIG_OVERRIDE = "$repo\config"
$env:SUBSTANCE_PAINTER_PLUGINS_PATH = "$repo\config\bundles\tk-substancepainter\painter;$repo\tests\painter_selftest"
$env:SGTK_CORE_PYTHON_PATH = "$cache\app_store\tk-core\v0.24.6\python"
$env:SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS = $cache
$env:SHOTGUN_ENTITY_TYPE = $EntityType
$env:SHOTGUN_ENTITY_ID = "$EntityId"
$env:SG_PIPELINE_SELFTEST_OUT = $out
# where the self-test saves its Painter project and exports textures
$env:SG_PIPELINE_SELFTEST_WORK = Join-Path (Split-Path -Parent $repo) "sg_pipeline_work\testAsset\texture"

$process = Start-Process -FilePath $painter -PassThru
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while (-not (Test-Path $out) -and -not $process.HasExited -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
}

if (Test-Path $out) {
    Get-Content $out
    # the result is in; Painter sometimes lingers without a window after closing
    if (-not $process.WaitForExit(30000)) {
        Stop-Process -Id $process.Id -Force -Confirm:$false
        $process.WaitForExit(10000) | Out-Null
        "note: the test's Painter (pid $($process.Id)) did not exit by itself and was stopped."
    }
} elseif ($process.HasExited) {
    "Painter exited (code $($process.ExitCode)) without writing a result."
} else {
    "Timed out after $TimeoutSeconds s; Painter (pid $($process.Id)) was left running."
}
"painter_still_running: $(-not $process.HasExited)"
