@echo off
rem Starts Substance 3D Painter with the Flow Production Tracking menu, using
rem the config in this repo.
rem
rem   painter_dev.bat                 start in the test project (Project 91)
rem   painter_dev.bat Task 5827       start in a task
rem
rem Sign in with the Flow Production Tracking desktop app first.

setlocal
set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"
set "SG_DESKTOP_CACHE=C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"

rem colour: the project's OCIO config, as the desktop app sets it (before_app_launch.py)
set "OCIO=%REPO%\config\color\sg_pipeline.ocio"
set "TK_BOOTSTRAP_CONFIG_OVERRIDE=%REPO%\config"
set "SUBSTANCE_PAINTER_PLUGINS_PATH=%REPO%\config\bundles\tk-substancepainter\painter"
set "SGTK_CORE_PYTHON_PATH=%SG_DESKTOP_CACHE%\app_store\tk-core\v0.24.6\python"
set "SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS=%SG_DESKTOP_CACHE%"

set "SHOTGUN_ENTITY_TYPE=%~1"
set "SHOTGUN_ENTITY_ID=%~2"
if "%SHOTGUN_ENTITY_TYPE%"=="" set "SHOTGUN_ENTITY_TYPE=Project"
if "%SHOTGUN_ENTITY_ID%"=="" set "SHOTGUN_ENTITY_ID=91"

echo Starting Painter in %SHOTGUN_ENTITY_TYPE% %SHOTGUN_ENTITY_ID% with config %TK_BOOTSTRAP_CONFIG_OVERRIDE%
start "" "C:\Program Files\Adobe\Adobe Substance 3D Painter\Adobe Substance 3D Painter.exe"
endlocal
