"""
sg_pipeline: Nuke startup, on NUKE_PATH when Nuke is launched from the pipeline
(config/hooks/tk-multi-launchapp/before_app_launch.py, launch scripts).

Nuke does not use $OCIO by itself: new scripts start in Nuke's own colour
management. This makes every new script use OCIO with the project's config
(config/color/sg_pipeline.ocio), so comp sees the same colour as Maya, Katana
and Mari. Scripts saved with other settings keep them when opened.
"""

import os

import nuke

_config = os.environ.get("OCIO")
if _config and os.path.isfile(_config):
    nuke.knobDefault("Root.colorManagement", "OCIO")
    nuke.knobDefault("Root.OCIO_config", "custom")
    nuke.knobDefault("Root.customOCIOConfigPath", _config.replace("\\", "/"))
