@echo off
rem Starts Katana with the Arnold plug-in (KtoA) and the Flow Production
rem Tracking menu, using the config in this repo.
rem
rem   katana_dev.bat                 start in the test project (Project 91)
rem   katana_dev.bat Task 5827       start in a task
rem
rem Sign in with the Flow Production Tracking desktop app first.
rem
rem To change versions, edit KATANA_HOME and KTOA_ROOT below. The KtoA build
rem must match the Katana release line (kat9.0 for Katana 9.0). If the KTOA_ROOT
rem folder does not exist Katana starts without Arnold.

setlocal
set "KATANA_HOME=C:\Program Files\Katana9.0v4"
set "KTOA_ROOT=%USERPROFILE%\ktoa\ktoa-4.5.4.1-kat9.0-windows"

set "REPO=%~dp0.."
for %%I in ("%REPO%") do set "REPO=%%~fI"
set "SG_DESKTOP_CACHE=C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
set "KATANAUSD_ROOT=%KATANA_HOME%\plugins\Resources\Usd"

if not exist "%KATANA_HOME%\bin\katanaBin.exe" echo Katana not found in %KATANA_HOME% & exit /b 1

rem ---- 1. Arnold (same settings as KtoA's own launchKtoA.bat)
if not exist "%KTOA_ROOT%\bin" goto no_arnold
set "DEFAULT_RENDERER=arnold"
set "USD_KATANA_ALLOW_CUSTOM_MATERIAL_SCOPES=true"
set "PATH=%KTOA_ROOT%\bin;%KATANAUSD_ROOT%\lib;%KATANAUSD_ROOT%\plugin\Libs;%PATH%"
set "KATANA_RESOURCES=%KTOA_ROOT%;%KATANAUSD_ROOT%\plugin;%KTOA_ROOT%\USD\KatanaUsdArnold;%KATANA_RESOURCES%"
set "FNPXR_PLUGINPATH=%KTOA_ROOT%\USD\Viewport;%FNPXR_PLUGINPATH%"
set "PYTHONPATH=%KATANAUSD_ROOT%\lib\python;%PYTHONPATH%"
echo Arnold: %KTOA_ROOT%
goto arnold_done
:no_arnold
echo Arnold: not loaded, %KTOA_ROOT% does not exist
:arnold_done

rem ---- 2. Flow Production Tracking, in front of what is already there
set "KATANA_RESOURCES=%REPO%\config\bundles\tk-katana\katana_resources;%KATANA_RESOURCES%"
rem colour: the project's OCIO config, as the desktop app sets it (before_app_launch.py)
set "OCIO=%REPO%\config\color\sg_pipeline.ocio"
set "TK_BOOTSTRAP_CONFIG_OVERRIDE=%REPO%\config"
set "SGTK_CORE_PYTHON_PATH=%SG_DESKTOP_CACHE%\app_store\tk-core\v0.24.6\python"
set "SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS=%SG_DESKTOP_CACHE%"

set "SHOTGUN_ENTITY_TYPE=%~1"
set "SHOTGUN_ENTITY_ID=%~2"
if "%SHOTGUN_ENTITY_TYPE%"=="" set "SHOTGUN_ENTITY_TYPE=Project"
if "%SHOTGUN_ENTITY_ID%"=="" set "SHOTGUN_ENTITY_ID=91"

echo Starting Katana in %SHOTGUN_ENTITY_TYPE% %SHOTGUN_ENTITY_ID% with config %TK_BOOTSTRAP_CONFIG_OVERRIDE%
start "" "%KATANA_HOME%\bin\katanaBin.exe"
endlocal
