# Installs the ShotGrid nodes into Griptape Nodes' sandbox library: copies
# sg_pipeline_nodes.py and sg_pipeline_nodes_3d.py there with this repo's path
# filled in.
#
#   powershell -File griptape\install.ps1 [-Workspace <Griptape workspace folder>]
#
# Griptape picks the files up at its next start.

param(
    [string]$Workspace = (Join-Path $env:USERPROFILE "Documents\GriptapeNodes"),
    [string]$SandboxFolder = "sandbox_library"
)

$repo = Split-Path -Parent $PSScriptRoot
$sandbox = Join-Path $Workspace $SandboxFolder
New-Item -ItemType Directory -Force $sandbox | Out-Null

foreach ($name in "sg_pipeline_nodes.py", "sg_pipeline_nodes_3d.py") {
    $source = [IO.File]::ReadAllText((Join-Path $PSScriptRoot $name))
    $target = Join-Path $sandbox $name
    [IO.File]::WriteAllText($target, $source.Replace("@SG_PIPELINE_REPO@", $repo), (New-Object System.Text.UTF8Encoding($false)))
    "Installed $target"
}
