@echo off
rem Starts the Flow Production Tracking desktop app using the config in this
rem repo instead of the stock basic config. Anything launched from it (Maya,
rem Nuke, ...) inherits the override.
rem
rem Quit the desktop app completely (tray icon > Quit) before running this.

set "TK_BOOTSTRAP_CONFIG_OVERRIDE=%~dp0..\config"
for %%I in ("%TK_BOOTSTRAP_CONFIG_OVERRIDE%") do set "TK_BOOTSTRAP_CONFIG_OVERRIDE=%%~fI"
echo Using Toolkit config: %TK_BOOTSTRAP_CONFIG_OVERRIDE%
start "" "C:\Program Files\Shotgun\Shotgun.exe"
