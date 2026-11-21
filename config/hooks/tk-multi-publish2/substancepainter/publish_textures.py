"""
Exports one map of one Painter texture set and publishes it to ShotGrid.

    hook: "{self}/publish_file.py:{config}/tk-multi-publish2/substancepainter/publish_textures.py"

The textures are written next to the Painter project, one file per UDIM tile:

    <project folder>/publish/textures/<project name>/<texture set>_<map>.<UDIM>.png

and registered as one "Texture" publish per texture set and map, named
"<texture set>_<map>", with the project's version number. The path stored in
ShotGrid keeps the literal <UDIM> token, which is what Maya and Mari expect.

If the project was created from a published mesh (see the loader's "Create
Painter Project" action) that mesh is recorded as what the textures were made
from.
"""

import os

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

PUBLISH_TYPE = "Texture"
UDIM_TOKEN = "<UDIM>"
FILE_FORMAT = "png"
PRESET_NAME = "sg_pipeline"


class SubstancePainterTexturesPublishPlugin(HookBaseClass):
    @property
    def description(self):
        return """
        <p>Exports this map of the texture set as PNG files, one per UDIM tile,
        next to the Painter project
        (<code>publish/textures/&lt;project name&gt;/</code>) and publishes
        them to Flow Production Tracking as one <b>Texture</b>.</p>
        """

    @property
    def item_filters(self):
        return ["substancepainter.textures"]

    def accept(self, settings, item):
        return {"accepted": True, "checked": True}

    def validate(self, settings, item):
        import substance_painter.export as sp_export
        import substance_painter.project as sp_project

        project_path = sp_project.file_path()
        if not project_path:
            error_msg = "Save the Painter project before publishing its textures."
            self.logger.error(error_msg)
            raise Exception(error_msg)

        texture_set = item.properties["texture_set"]
        map_name = item.properties["texture_map"]
        export_dir = textures_dir_for_project(project_path)

        config = self._export_config(item, export_dir)
        try:
            would_export = sp_export.list_project_textures(config)
        except ValueError as e:
            error_msg = "Painter cannot export %s %s: %s" % (texture_set, map_name, e)
            self.logger.error(error_msg)
            raise Exception(error_msg)
        if not any(would_export.values()):
            error_msg = "Painter has nothing to export for %s %s." % (texture_set, map_name)
            self.logger.error(error_msg)
            raise Exception(error_msg)

        publish_path = os.path.join(
            export_dir, "%s_%s.%s.%s" % (texture_set, map_name, UDIM_TOKEN, FILE_FORMAT)
        )
        item.properties["path"] = publish_path
        item.properties["publish_path"] = publish_path
        item.properties["publish_type"] = PUBLISH_TYPE
        item.properties["publish_name"] = "%s_%s" % (texture_set, map_name)
        item.properties["publish_version"] = (
            self.parent.util.get_version_number(project_path) or 1
        )
        item.properties["export_config"] = config

        self.logger.info("Textures will be exported to: %s" % publish_path)
        return super().validate(settings, item)

    def publish(self, settings, item):
        import substance_painter.export as sp_export

        result = sp_export.export_project_textures(item.properties["export_config"])
        written = [path for paths in result.textures.values() for path in paths]
        if result.status != sp_export.ExportStatus.Success or not written:
            raise Exception(
                "Painter did not export %s (%s): %s"
                % (item.name, result.status, result.message)
            )
        item.properties["exported_files"] = written
        self.logger.info("Exported %d file(s) for %s" % (len(written), item.name))

        # The mesh these textures were painted on. It is linked by id: with no
        # storage roots configured, ShotGrid cannot find a publish by its path.
        source = source_publish()
        if source and source.get("id"):
            item.properties["publish_kwargs"] = {"dependency_ids": [source["id"]]}

        super().publish(settings, item)

    def _export_config(self, item, export_dir):
        return export_config(
            export_dir,
            item.properties["texture_set"],
            item.properties["texture_map"],
            item.properties["texture_spec"],  # from the collector's TEXTURE_MAPS
            item.properties["has_uv_tiles"],
        )


def textures_dir_for_project(project_path):
    """<project folder>/publish/textures/<project name>"""
    project_path = sgtk.util.ShotgunPath.normalize(project_path)
    project_dir, project_file = os.path.split(project_path)
    return os.path.join(
        project_dir, "publish", "textures", os.path.splitext(project_file)[0]
    )


def export_config(export_dir, texture_set, map_name, spec, has_uv_tiles):
    """Painter export configuration for a single map of a single texture set."""
    source_type, source_name = spec["source"]
    channels = [
        {
            "destChannel": channel,
            "srcChannel": channel,
            "srcMapType": source_type,
            "srcMapName": source_name,
        }
        for channel in (("R", "G", "B") if spec["color"] else ("L",))
    ]
    # always write a UDIM number so downstream applications see one naming
    file_name = "$textureSet_%s.%s" % (map_name, "$udim" if has_uv_tiles else "1001")

    return {
        "exportPath": export_dir.replace("\\", "/"),
        "exportShaderParams": False,
        "defaultExportPreset": PRESET_NAME,
        "exportPresets": [
            {
                "name": PRESET_NAME,
                "maps": [
                    {
                        "fileName": file_name,
                        "channels": channels,
                        "parameters": {
                            "fileFormat": FILE_FORMAT,
                            "bitDepth": spec["bit_depth"],
                            "dithering": False,
                            "paddingAlgorithm": "infinite",
                        },
                    }
                ],
            }
        ],
        "exportList": [{"rootPath": texture_set}],
    }


def source_publish():
    """The publish the project's mesh came from, or None."""
    import substance_painter.project as sp_project

    try:
        return sp_project.Metadata("sg_pipeline").get("source_publish")
    except Exception:
        return None
