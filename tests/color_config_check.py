"""
Run inside Maya (mayapy), Nuke (-t), Katana (--script) or Mari (-x) by
tests/run_color_check.ps1, with OCIO set to config/color/sg_pipeline.ocio the
way the desktop app's before_app_launch hook sets it. Prints one line,
RESULT <json>, saying which OCIO config the application uses and how it reads
an 8-bit texture and an EXR render. No ShotGrid.
"""

import json
import os
import sys
import traceback

result = {"OCIO": os.environ.get("OCIO"), "host": None, "error": None}


def ocio_library():
    """The application's own PyOpenColorIO: config name and file rules."""
    import PyOpenColorIO as ocio

    config = ocio.GetCurrentConfig()
    result["ocio_version"] = ocio.GetVersion()
    result["config_name"] = config.getName()
    result["png"] = config.getColorSpaceFromFilepath("lantern_basecolor.1001.png")[0]
    result["exr"] = config.getColorSpaceFromFilepath("beauty.0001.exr")[0]
    # getRoleColorSpace is OCIO 2.3+; Mari 7.1 has 2.2
    result["scene_linear"] = config.getColorSpace("scene_linear").getName()


try:
    if "maya" in os.path.basename(sys.executable).lower():
        result["host"] = "maya"
        import maya.standalone

        maya.standalone.initialize()
        import maya.cmds as cmds

        result["config_path"] = cmds.colorManagementPrefs(query=True, configFilePath=True)
        result["cm_enabled"] = cmds.colorManagementPrefs(query=True, cmEnabled=True)
        result["rendering_space"] = cmds.colorManagementPrefs(query=True, renderingSpaceName=True)
        node = cmds.shadingNode("file", asTexture=True, isColorManaged=True)
        cmds.setAttr(node + ".fileTextureName", "C:/x/lantern_basecolor.1001.png", type="string")
        result["maya_png_file_node"] = cmds.getAttr(node + ".colorSpace")
        ocio_library()
    elif "nuke" in sys.modules or "nuke" in os.path.basename(sys.executable).lower():
        import nuke

        result["host"] = "nuke"
        root = nuke.root()
        result["color_management"] = root["colorManagement"].value()
        result["ocio_config_knob"] = root["OCIO_config"].value()
        result["working_space"] = root["workingSpaceLUT"].value()
        read = nuke.nodes.Read(file="C:/x/lantern_basecolor.1001.png")
        result["nuke_png_read"] = read["colorspace"].value()
        ocio_library()
    else:
        try:
            from Katana import NodegraphAPI  # noqa: F401

            result["host"] = "katana"
        except ImportError:
            import mari

            result["host"] = "mari"
            result["mari_version"] = mari.app.version().string()
        ocio_library()
except Exception:
    result["error"] = traceback.format_exc()

print("RESULT " + json.dumps(result))
if result["host"] in ("katana", "mari"):
    sys.stdout.flush()
    if result["host"] == "mari":
        import mari

        mari.app.quit()
