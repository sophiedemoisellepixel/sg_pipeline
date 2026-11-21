"""
Exports the Maya session geometry to USD and publishes it to ShotGrid.

Configured in env/includes/maya/apps.yml as:

    hook: "{self}/publish_file.py:{config}/tk-multi-publish2/maya/publish_usd.py"

The basic config has no path templates, so the USD file is written next to the
scene, in a "publish/usd" sub folder, keeping the scene's name and version:

    <scene folder>/publish/usd/<scene name>.usd

If something is selected only the selection is exported, otherwise everything
visible is.
"""

import os

import maya.cmds as cmds
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

USD_PLUGIN = "mayaUsdPlugin"
PUBLISH_TYPE = "USD Geometry"


class MayaUsdPublishPlugin(HookBaseClass):
    @property
    def description(self):
        return """
        <p>Exports the session geometry to a USD file next to the scene
        (<code>publish/usd/&lt;scene name&gt;.usd</code>) and publishes it to
        Flow Production Tracking as <b>USD Geometry</b>.</p>
        <p>If nodes are selected only the selection is exported, otherwise all
        visible geometry is. UVs and material assignments are included so the
        file can be loaded in Substance Painter, Mari, Katana and Nuke.</p>
        """

    @property
    def settings(self):
        plugin_settings = super().settings or {}
        plugin_settings.update(
            {
                "Mesh Scheme": {
                    "type": "str",
                    "default": "catmullClark",
                    "description": "USD subdivision scheme written on meshes: "
                    "catmullClark, none, loop or bilinear.",
                },
                "Convert Materials To": {
                    "type": "list",
                    "default": ["UsdPreviewSurface"],
                    "description": "Material conversions passed to mayaUSDExport.",
                },
            }
        )
        return plugin_settings

    @property
    def item_filters(self):
        return ["maya.session.usd"]

    def accept(self, settings, item):
        if not _ensure_usd_plugin():
            self.logger.warning(
                "The '%s' Maya plugin could not be loaded. USD publishing is "
                "not available." % USD_PLUGIN
            )
            return {"accepted": False}
        return {"accepted": True, "checked": True}

    def validate(self, settings, item):
        scene_path = cmds.file(query=True, sceneName=True)
        if not scene_path:
            error_msg = "The Maya session has not been saved."
            self.logger.error(error_msg)
            raise Exception(error_msg)

        if not cmds.ls(geometry=True, noIntermediate=True):
            error_msg = "There is no geometry in the scene to export to USD."
            self.logger.error(error_msg)
            raise Exception(error_msg)

        usd_path = usd_path_for_scene(scene_path)

        # the base file publisher reads everything it needs from these
        item.properties["path"] = usd_path
        item.properties["publish_path"] = usd_path
        item.properties["publish_type"] = PUBLISH_TYPE

        self.logger.info("USD will be exported to: %s" % usd_path)
        return super().validate(settings, item)

    def publish(self, settings, item):
        usd_path = item.properties["path"]
        self.export_usd(
            usd_path,
            mesh_scheme=settings["Mesh Scheme"].value,
            convert_materials_to=settings["Convert Materials To"].value,
        )

        # the session item's publish (if it ran) becomes an upstream dependency
        session_path = cmds.file(query=True, sceneName=True)
        if session_path:
            item.properties["publish_dependencies"] = [
                sgtk.util.ShotgunPath.normalize(session_path)
            ]

        # register the exported file with ShotGrid
        super().publish(settings, item)

    def export_usd(self, usd_path, mesh_scheme="catmullClark", convert_materials_to=None):
        """
        Write the session geometry to ``usd_path``.

        :returns: The path written.
        """
        if not _ensure_usd_plugin():
            raise Exception("The '%s' Maya plugin is not available." % USD_PLUGIN)

        self.parent.ensure_folder_exists(os.path.dirname(usd_path))

        export_args = {
            "file": usd_path.replace("\\", "/"),
            # only honour the selection if it actually contains geometry
            "selection": bool(
                cmds.ls(selection=True, dagObjects=True, geometry=True, noIntermediate=True)
            ),
            "exportUVs": True,
            "exportVisibility": True,
            "stripNamespaces": True,
            "defaultMeshScheme": mesh_scheme,
            "shadingMode": "useRegistry",
            "convertMaterialsTo": list(convert_materials_to or ["UsdPreviewSurface"]),
        }

        frame_range = _animation_range()
        if frame_range:
            export_args["frameRange"] = frame_range

        self.logger.debug("mayaUSDExport(%s)" % export_args)
        cmds.mayaUSDExport(**export_args)

        if not os.path.exists(usd_path):
            raise Exception("USD export did not produce a file: %s" % usd_path)

        self.logger.info("Exported USD: %s" % usd_path)
        return usd_path


def usd_path_for_scene(scene_path):
    """<scene folder>/publish/usd/<scene name>.usd"""
    scene_path = sgtk.util.ShotgunPath.normalize(scene_path)
    scene_dir, scene_file = os.path.split(scene_path)
    scene_name = os.path.splitext(scene_file)[0]
    return os.path.join(scene_dir, "publish", "usd", "%s.usd" % scene_name)


def _ensure_usd_plugin():
    try:
        if not cmds.pluginInfo(USD_PLUGIN, query=True, loaded=True):
            cmds.loadPlugin(USD_PLUGIN, quiet=True)
        return True
    except Exception:
        return False


def _animation_range():
    """The timeline range if anything is animated, otherwise None (static export)."""
    if not cmds.ls(type="animCurve"):
        return None
    return (
        cmds.playbackOptions(query=True, minTime=True),
        cmds.playbackOptions(query=True, maxTime=True),
    )
