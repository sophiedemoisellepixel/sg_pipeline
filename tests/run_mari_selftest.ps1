# Runs Mari headless (terminal mode, no window) with the Toolkit engine and
# executes tests\mari_selftest.py in it. Uses the textures exported by the last
# run of tests\run_painter_selftest.ps1. Only reads from ShotGrid.
#
#   powershell -File tests\run_mari_selftest.ps1 [-EntityType Task] [-EntityId 5827]

param(
    [string]$EntityType = "Project",
    [int]$EntityId = 91,
    [int]$TimeoutSeconds = 420,
    # load the Texture publishes registered in ShotGrid instead of the files
    # listed by the last Painter self-test
    [switch]$SiteTextures,
    # WRITES to ShotGrid: registers the exported channels as publishes
    [switch]$Publish
)
$env:SG_PIPELINE_SELFTEST_PUBLISH = if ($Publish) { "1" } else { "0" }
# where the Mari publisher exports channels during the self-test
$env:SG_PIPELINE_MARI_EXPORT_ROOT = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "sg_pipeline_work\mari_publish"
$env:SG_PIPELINE_USE_SITE_TEXTURES = if ($SiteTextures) { "1" } else { "0" }

$repo = Split-Path -Parent $PSScriptRoot
$cache = "C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
# the version the pipeline launches; Mari 8.0v1 exits without running -x scripts here
$mari = Get-Item "C:\Program Files\Mari7.1v2\Bundle\bin\Mari7.1v2.exe"
$out = Join-Path $env:TEMP "sg_pipeline_mari_selftest.json"
$log = Join-Path $env:TEMP "sg_pipeline_mari_selftest.log"
Remove-Item $out, $log -ErrorAction SilentlyContinue

$env:TK_BOOTSTRAP_CONFIG_OVERRIDE = "$repo\config"
$env:MARI_SCRIPT_PATH = "$repo\config\bundles\tk-mari\mari_startup"
$env:SGTK_CORE_PYTHON_PATH = "$cache\app_store\tk-core\v0.24.6\python"
$env:SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS = $cache
$env:SHOTGUN_ENTITY_TYPE = $EntityType
$env:SHOTGUN_ENTITY_ID = "$EntityId"
$env:SG_PIPELINE_SELFTEST_OUT = $out
$env:SG_PIPELINE_PAINTER_RESULT = Join-Path $env:TEMP "sg_pipeline_painter_selftest.json"

$process = Start-Process -FilePath $mari.FullName -ArgumentList "-x", "`"$repo\tests\mari_selftest.py`"" `
    -PassThru -RedirectStandardError $log -RedirectStandardOutput "$log.out"
if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    Stop-Process -Id $process.Id -Force -Confirm:$false
    "note: Mari (pid $($process.Id)) did not exit within $TimeoutSeconds s and was stopped."
}

if (Test-Path $out) {
    Get-Content $out
} else {
    "Mari wrote no result. Last lines of its output:"
    Get-Content $log, "$log.out" -ErrorAction SilentlyContinue | Select-Object -Last 40
}
