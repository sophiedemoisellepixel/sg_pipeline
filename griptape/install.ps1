# Registers the "ShotGrid Pipeline" library with Griptape Nodes, the same way
# an official library is registered: Griptape loads griptape-nodes-library.json
# (and the node files next to it) straight from this repo, so edits here are
# picked up after a library refresh or restart, with nothing to copy.
#
#   powershell -File griptape\install.ps1
#
# Copies of the nodes left in the sandbox library by the old installer are
# moved to sandbox_library\_moved_to_library so they do not show up twice.
# Restart Griptape Nodes afterwards.

param(
    [string]$Workspace = (Join-Path $env:USERPROFILE "Documents\GriptapeNodes"),
    [string]$Config = (Join-Path $env:APPDATA "Griptape Nodes\xdg_config_home\griptape_nodes\griptape_nodes_config.json"),
    [string]$Python = (Join-Path $env:LOCALAPPDATA "ai.griptape.nodes.desktop\current\resources\engine-bundle\python\python.exe")
)

$manifest = Join-Path $PSScriptRoot "griptape-nodes-library.json"
foreach ($required in $manifest, $Config, $Python) {
    if (-not (Test-Path $required)) { throw "Not found: $required" }
}

Copy-Item $Config "$Config.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
$script = @'
import json, sys
config, manifest = sys.argv[1], sys.argv[2]
data = json.load(open(config, encoding="utf-8"))
events = data.setdefault("app_events", {}).setdefault("on_app_initialization_complete", {})
paths = events.setdefault("libraries_to_register", [])
norm = lambda p: p.replace("\\", "/").lower()
if not any(norm(p) == norm(manifest) for p in paths):
    paths.append(manifest)
json.dump(data, open(config, "w", encoding="utf-8"), indent=2)
print("Registered " + manifest)
'@
# run from a file: Windows PowerShell drops the quotes of an inline -c script
$scriptFile = Join-Path $env:TEMP "sg_pipeline_register_library.py"
[IO.File]::WriteAllText($scriptFile, $script)
& $Python $scriptFile $Config $manifest
if ($LASTEXITCODE -ne 0) { throw "Could not register the library in $Config" }

$sandbox = Join-Path $Workspace "sandbox_library"
$moved = Join-Path $sandbox "_moved_to_library"
foreach ($name in "sg_pipeline_nodes.py", "sg_pipeline_nodes_3d.py") {
    $old = Join-Path $sandbox $name
    if (Test-Path $old) {
        New-Item -ItemType Directory -Force $moved | Out-Null
        Move-Item $old (Join-Path $moved $name) -Force
        "Moved the old sandbox copy of $name to $moved"
    }
}
"Restart Griptape Nodes to load the ShotGrid Pipeline library."
