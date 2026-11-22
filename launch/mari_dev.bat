@echo off
rem Starts Mari with the Flow Production Tracking menu, using the config in
rem this repo.
rem
rem   mari_dev.bat                 start in the test project (Project 91)
rem   mari_dev.bat Task 5827       start in a task
rem
rem Sign in with the Flow Production Tracking desktop app first.

setlocal
set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"
set "SG_DESKTOP_CACHE=C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"

rem colour: the project's OCIO config, as the desktop app sets it (before_app_launch.py)
set "OCIO=%REPO%\config\color\sg_pipeline.ocio"
set "TK_BOOTSTRAP_CONFIG_OVERRIDE=%REPO%\config"
set "MARI_SCRIPT_PATH=%REPO%\config\bundles\tk-mari\mari_startup"
set "SGTK_CORE_PYTHON_PATH=%SG_DESKTOP_CACHE%\app_store\tk-core\v0.24.6\python"
set "SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS=%SG_DESKTOP_CACHE%"

set "SHOTGUN_ENTITY_TYPE=%~1"
set "SHOTGUN_ENTITY_ID=%~2"
if "%SHOTGUN_ENTITY_TYPE%"=="" set "SHOTGUN_ENTITY_TYPE=Project"
if "%SHOTGUN_ENTITY_ID%"=="" set "SHOTGUN_ENTITY_ID=91"

echo Starting Mari in %SHOTGUN_ENTITY_TYPE% %SHOTGUN_ENTITY_ID% with config %TK_BOOTSTRAP_CONFIG_OVERRIDE%
start "" "C:\Program Files\Mari7.1v2\Bundle\bin\Mari7.1v2.exe"
endlocal
