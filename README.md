# sg_pipeline

Custom ShotGrid (Flow Production Tracking) Toolkit pipeline, built on a fork of
`tk-config-basic` v1.7.9. USD is the interchange format between applications.

## Layout

| Path | What it is |
| --- | --- |
| `config/` | The Toolkit pipeline configuration (fork of the basic config). |
| `config/hooks/` | Our custom hooks, referenced from the env files as `{config}/...`. |
| `config/bundles/` | In-house engines: `tk-substancepainter`, `tk-mari`, `tk-katana`. |
| `griptape/` | ShotGrid nodes for Griptape Nodes (`sg_pipeline_nodes.py`, `sg_pipeline_nodes_3d.py`), the model-to-USD converter, their installer and the ShotGrid bridge. |
| `launch/desktop_dev.bat` | Starts the desktop app with this config instead of the stock one. |
| `tests/` | Headless tests, run with `mayapy`. |

## Using it

1. Quit the Flow Production Tracking desktop app (tray icon > Quit).
2. Run `launch\desktop_dev.bat`.
3. Open the project and launch Maya from the desktop app.

The override is the `TK_BOOTSTRAP_CONFIG_OVERRIDE` environment variable, so
nothing is changed on the ShotGrid site. On this PC it is also set as a user
environment variable, so the desktop app uses this config however it is started;
delete that variable (Windows > Edit environment variables for your account) to
go back to the stock config. Config edits are picked up the next
time an application is launched.

## Links

| Link | Status |
| --- | --- |
| ShotGrid -> Maya | Publish: **Publish USD Geometry** (scene geometry -> `<scene folder>/publish/usd/<scene>.usd`, type `USD Geometry`). Load: **Create USD Stage**, **Import USD as Maya Geometry**. |
| Maya -> Substance Painter | In-house engine `config/bundles/tk-substancepainter` adds a **Flow Production Tracking** menu to Painter. Loader actions on `USD Geometry` publishes: **Create Painter Project**, **Update Mesh in Current Project**. Start Painter with `launch\painter_dev.bat [Task <id>]`. |
| Substance Painter -> Mari | Painter: **Publish...** exports each texture set's maps (base colour, roughness, metallic, normal, height, emissive, opacity) to `<project folder>/publish/textures/<project name>/<texture set>_<map>.<UDIM>.png` and publishes each as a `Texture`. Mari: in-house engine `config/bundles/tk-mari` with loader actions **Create Mari Project** / **Add to Current Project** (`USD Geometry`) and **Import as Layer** (`Texture`). Start Mari with `launch\mari_dev.bat [Task <id>]`. |
| Mari -> Maya | Mari: **Publish...** exports each channel flattened to `<export root>/<entity>/<mari project>/v###/<object>_<channel>.<UDIM>.png` (EXR above 8 bit) and publishes it as a `Texture`. The export root is `SG_PIPELINE_MARI_EXPORT_ROOT`, else `Documents/Mari/sg_pipeline_publish`. Maya: loader actions on `Texture` publishes, **Build Material from Textures** (standardSurface from all selected publishes, assigned to the selected meshes) and **Create Texture Node (UDIM)**. Also works on Painter's textures. |
| Maya -> Katana | In-house engine `config/bundles/tk-katana` adds a **Flow Production Tracking** menu to Katana. Loader action on `USD Geometry` publishes: **Create UsdIn Node**. Katana is always started with the Arnold plug-in (KtoA): the launcher picks the newest `~/ktoa/ktoa-*-kat<major.minor>-*` build matching the Katana version (override with `SG_PIPELINE_KTOA_ROOT`) and keeps existing `KATANA_RESOURCES` entries (3Delight). Start Katana with `launch\katana_dev.bat [Task <id>]`. Tested headless in Katana 9.0v4 with KtoA 4.5.4.1. |
| Katana -> Nuke | Katana: **Publish...** collects every Render node output that is written to a file and has frames on disk, and publishes it where it is as a `Rendered Image` (path `name.%04d.ext`, name `<project>_<render node>_<output>`, version from the project file's `v###`), linked to the publishes the loader brought in. Nuke: the stock **Create Read Node** action loads it with its frame range. |
| Nuke -> Griptape | Nuke: the stock publisher publishes Write node output; write PNG, JPEG or TIFF, which it registers as type `Image` (Griptape cannot read EXR). The stock publisher does not record which publishes the comp was made from. Griptape Nodes: **ShotGridLoadPublish** node finds a publish (newest by type and name, or by id) and outputs its image, file path and publish id. |
| Griptape -> everything | Griptape Nodes: **ShotGridPublishImage** node saves an image as PNG under `Documents/GriptapeNodes/sg_pipeline_publish` (or `SG_PIPELINE_GRIPTAPE_PUBLISH_ROOT`) and registers it as `Texture` (UDIM tile 1001; loads in Maya and Mari), `Image` or `Rendered Image` (loads in Nuke). Install the nodes with `griptape\install.ps1` and restart Griptape Nodes. They reach ShotGrid through `griptape\sg_bridge.py`, run with the desktop app's Python. |
| AI 3D -> everything | Griptape Nodes: **ShotGridPublish3D** node takes a generated model (the 3D Model output of Rodin or Tripo, Load 3D, or a file path: GLB, glTF, USDZ, FBX, OBJ), converts it with `griptape/mesh_to_usd.py` and publishes it as `USD Geometry`, so every loader above picks it up. GLB/glTF are read in metres and written in cm with node transforms baked in and UVs kept (face-varying, which Mari needs); the PBR material becomes a UsdPreviewSurface with its textures next to the USD. USDZ is unpacked; FBX and OBJ go through Maya. Draco or meshopt compressed GLBs are refused. The generated file is kept in a `source` folder next to the USD. |
| Maya -> Nuke | Nuke (stock `tk-nuke` engine) loader actions on `USD Geometry` publishes: **Create GeoImport Node (USD 3D)** and **Create ReadGeo Node (Classic 3D)**. Tested in Nuke 17.1v3. |

## Tests

```
"C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe" tests\test_maya_usd.py
```

Uses the sign-in saved by the desktop app and only reads from ShotGrid.

| Test | Runs in | Writes to ShotGrid |
| --- | --- | --- |
| `tests\test_maya_usd.py` | `mayapy` | no |
| `tests\integration_publish_usd.py` | `mayapy` | yes: Asset, Task and one publish per run |
| `tests\test_painter_engine.py` | Painter's `resources\pythonsdk\python.exe`, with a stub of Painter's API | no |
| `tests\run_painter_selftest.ps1` | a new Painter window, which closes itself; saves a test project and exports textures under `sg_pipeline_work` | no |
| `tests\run_mari_selftest.ps1` | Mari headless (no window); needs a previous Painter self-test run for the textures | no |
| `tests\test_maya_textures.py` | `mayapy`; needs a previous Mari self-test run for the Mari textures | no |
| `tests\test_nuke_usd.py` | `Nuke17.1.exe -t -i` (terminal mode with the interactive login licence); needs a previous Katana self-test run for the render | only with `SG_PIPELINE_SELFTEST_PUBLISH=1` (the PNG comp frames) |
| `tests\run_katana_selftest.ps1` | Katana in script mode (no window), with Arnold and the engine; renders two frames on first run | only with `-Publish` (one Rendered Image publish) |
| `tests\test_griptape_nodes.py` | Griptape engine's `python.exe`, outside the Griptape app | only with `--publish` (one Texture publish) |
| `tests\test_mesh_to_usd.py` | Griptape engine's `python.exe`; also uses Katana's USD library and `mayapy` | no (its node dry run only reads, and is skipped when not signed in) |
| `tests\run_mesh_consumers_check.ps1 -Usd <file>` | Painter (window) and Mari 7.1v2 (headless) build a project from a USD file, no ShotGrid | no |
| `tests\check_katana_launcher.py` | the desktop app's `Python3\python.exe`; launches nothing | no |
| `tests\check_desktop_launcher.py` | the desktop app's `Python3\python.exe` | only with `--create` (adds the missing Painter, Mari and Katana Software entries) |
