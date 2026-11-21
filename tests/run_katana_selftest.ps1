# Runs Katana in script mode (no window) with the Arnold plug-in and the
# Toolkit engine, and executes tests\katana_selftest.py in it. Only reads from
# ShotGrid.
#
#   powershell -File tests\run_katana_selftest.ps1 [-EntityType Task] [-EntityId 5827]

param(
    [string]$EntityType = "Project",
    [int]$EntityId = 91,
    [int]$TimeoutSeconds = 300,
    # WRITES to ShotGrid: registers the rendered frames as a publish
    [switch]$Publish,
    [string]$KatanaHome = "C:\Program Files\Katana9.0v4",
    [string]$KtoaRoot = (Join-Path $env:USERPROFILE "ktoa\ktoa-4.5.4.1-kat9.0-windows")
)

$repo = Split-Path -Parent $PSScriptRoot
$cache = "C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
$usd = "$KatanaHome\plugins\Resources\Usd"
$out = Join-Path $env:TEMP "sg_pipeline_katana_selftest.json"
$log = Join-Path $env:TEMP "sg_pipeline_katana_selftest.log"
Remove-Item $out, $log, "$log.out" -ErrorAction SilentlyContinue

# the same environment as launch\katana_dev.bat
$env:DEFAULT_RENDERER = "arnold"
$env:USD_KATANA_ALLOW_CUSTOM_MATERIAL_SCOPES = "true"
$env:PATH = "$KtoaRoot\bin;$usd\lib;$usd\plugin\Libs;$env:PATH"
$env:KATANA_RESOURCES = "$repo\config\bundles\tk-katana\katana_resources;$KtoaRoot;$usd\plugin;$KtoaRoot\USD\KatanaUsdArnold;$env:KATANA_RESOURCES"
$env:FNPXR_PLUGINPATH = "$KtoaRoot\USD\Viewport;$env:FNPXR_PLUGINPATH"
$env:PYTHONPATH = "$usd\lib\python;$env:PYTHONPATH"
$env:TK_BOOTSTRAP_CONFIG_OVERRIDE = "$repo\config"
$env:SGTK_CORE_PYTHON_PATH = "$cache\app_store\tk-core\v0.24.6\python"
$env:SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS = $cache
$env:SHOTGUN_ENTITY_TYPE = $EntityType
$env:SHOTGUN_ENTITY_ID = "$EntityId"
$env:SG_PIPELINE_SELFTEST_OUT = $out
$env:SG_PIPELINE_SELFTEST_PUBLISH = if ($Publish) { "1" } else { "0" }
# where the self-test saves its render scene and Arnold writes the frames
$work = Join-Path (Split-Path -Parent $repo) "sg_pipeline_work\katana_test"
New-Item -ItemType Directory -Force $work | Out-Null
$env:SG_PIPELINE_KATANA_WORK = $work

function Invoke-Katana([string[]]$arguments, [int]$seconds) {
    $process = Start-Process -FilePath "$KatanaHome\bin\katanaBin.exe" -ArgumentList $arguments `
        -PassThru -RedirectStandardError $log -RedirectStandardOutput "$log.out" -WindowStyle Hidden
    if (-not $process.WaitForExit($seconds * 1000)) {
        Stop-Process -Id $process.Id -Force -Confirm:$false
        "note: Katana (pid $($process.Id)) did not exit within $seconds s and was stopped."
    }
}

Invoke-Katana @("--script=`"$repo\tests\katana_selftest.py`"") $TimeoutSeconds

# first run on this machine: render the scene the self-test saved, then test again
if ((Test-Path $out) -and (Get-Content $out -Raw | ConvertFrom-Json).needs_render) {
    "rendering frames 1-2 of the test scene with Arnold..."
    Invoke-Katana @("--batch", "--katana-file=`"$work\katana_test_v001.katana`"", "--render-node=Render", "-t", "1-2") $TimeoutSeconds
    Remove-Item $out -ErrorAction SilentlyContinue
    Invoke-Katana @("--script=`"$repo\tests\katana_selftest.py`"") $TimeoutSeconds
}
if (Test-Path $out) {
    Get-Content $out
} else {
    "Katana wrote no result. Last lines of its output:"
    Get-Content $log, "$log.out" -ErrorAction SilentlyContinue | Select-Object -Last 40
}
