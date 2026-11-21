"""
Loader actions for Mari (Painter -> Mari, and geometry from Maya).

Mapped in env/includes/mari/apps.yml:

  USD Geometry
    mari_new_project     Create a Mari project from the published mesh.
    mari_add_geometry    Add the published mesh to the open project.

  Texture
    mari_import_layer    Import the published textures (one file per UDIM) as
                         a new paint layer on the current object. The channel
                         is named after the map ("basecolor", "roughness", ...)
                         and is created if it does not exist yet.

The publish a project's mesh came from is stored in the project metadata
("sg_pipeline_source_publish", JSON) so texture publishes from Mari can be
linked back to the geometry.
"""

import json
import os

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

SOURCE_PUBLISH_METADATA = "sg_pipeline_source_publish"
UDIM_TOKEN = "<UDIM>"
DEFAULT_CHANNEL = "basecolor"
DEFAULT_CHANNEL_SIZE = 2048

ACTIONS = {
    "mari_new_project": (
        "Create Mari Project",
        "Creates a new Mari project from this mesh.",
    ),
    "mari_add_geometry": (
        "Add to Current Project",
        "Adds this mesh to the open Mari project as a new object.",
    ),
    "mari_import_layer": (
        "Import as Layer",
        "Imports these textures as a new paint layer on the current object.",
    ),
}


class MariActions(HookBaseClass):
    def generate_actions(self, sg_publish_data, actions, ui_area):
        return [
            {
                "name": name,
                "params": None,
                "caption": ACTIONS[name][0],
                "description": ACTIONS[name][1],
            }
            for name in actions
            if name in ACTIONS
        ]

    def execute_multiple_actions(self, actions):
        for single_action in actions:
            self.execute_action(
                single_action["name"],
                single_action["params"],
                single_action["sg_publish_data"],
            )

    def execute_action(self, name, params, sg_publish_data):
        path = self.get_publish_path(sg_publish_data)

        if name == "mari_new_project":
            return self._new_project(path, sg_publish_data)
        if name == "mari_add_geometry":
            return self._add_geometry(path, sg_publish_data)
        if name == "mari_import_layer":
            return self._import_layer(path, sg_publish_data)

    # ---- geometry

    def _new_project(self, path, sg_publish_data):
        import mari

        _require_file(path)
        if mari.projects.current() is not None:
            raise Exception(
                "A Mari project is already open. Save and close it, then try "
                "again, or use 'Add to Current Project'."
            )

        # Mari needs at least one channel to create a project
        channel = mari.ChannelInfo(
            DEFAULT_CHANNEL, DEFAULT_CHANNEL_SIZE, DEFAULT_CHANNEL_SIZE, mari.Image.DEPTH_BYTE
        )
        mari.projects.create(
            project_name(sg_publish_data), path.replace("\\", "/"), [channel]
        )
        project = mari.projects.current()
        project.setMetadata(
            SOURCE_PUBLISH_METADATA, json.dumps(source_publish_record(sg_publish_data, path))
        )
        self.parent.logger.info("Created Mari project '%s' from %s" % (project.name(), path))
        return project

    def _add_geometry(self, path, sg_publish_data):
        import mari

        _require_file(path)
        if mari.projects.current() is None:
            raise Exception("There is no Mari project open to add the mesh to.")
        objects = mari.geo.load(path.replace("\\", "/"))
        self.parent.logger.info("Added %d object(s) from %s" % (len(objects or []), path))
        return objects

    # ---- textures

    def _import_layer(self, path, sg_publish_data):
        import mari

        if mari.projects.current() is None:
            raise Exception("Open or create a Mari project before importing textures.")
        geo = mari.geo.current()
        if geo is None:
            raise Exception("Select an object in Mari to import the textures onto.")

        template = path.replace("\\", "/").replace(UDIM_TOKEN, "$UDIM")
        if not _udim_files(path):
            raise Exception("No texture files found on disk for '%s'" % path)

        channel_name = channel_name_for(sg_publish_data)
        channel = geo.findChannel(channel_name)
        if channel is None:
            channel = geo.createChannel(
                channel_name, DEFAULT_CHANNEL_SIZE, DEFAULT_CHANNEL_SIZE, 8
            )

        layer = channel.createPaintableLayer(layer_name_for(sg_publish_data))
        # resize the Mari patches to the size of the incoming images
        layer.importImages(template, mari.ImageSet.SCALE_THE_PATCH)
        self.parent.logger.info(
            "Imported %s into channel '%s', layer '%s'" % (template, channel_name, layer.name())
        )
        return layer


def channel_name_for(sg_publish_data):
    """
    The Mari channel for a texture publish. Painter publishes are named
    "<texture set>_<map>", so the map is what follows the last underscore.
    """
    name = sg_publish_data.get("name") or sg_publish_data.get("code") or ""
    name = name.split(".")[0]
    return name.rsplit("_", 1)[-1] or DEFAULT_CHANNEL


def layer_name_for(sg_publish_data):
    """e.g. testMtlSG_basecolor_v003"""
    name = (sg_publish_data.get("name") or sg_publish_data.get("code") or "texture").split(".")[0]
    version = sg_publish_data.get("version_number")
    return "%s_v%03d" % (name, version) if version else name


def project_name(sg_publish_data):
    """e.g. testAsset_testAsset_model_v003"""
    entity = sg_publish_data.get("entity") or {}
    name = (sg_publish_data.get("name") or sg_publish_data.get("code") or "mesh").split(".")[0]
    parts = [entity.get("name"), name]
    version = sg_publish_data.get("version_number")
    if version:
        parts.append("v%03d" % version)
    return "_".join(p for p in parts if p)


def source_publish_record(sg_publish_data, path):
    entity = sg_publish_data.get("entity") or {}
    task = sg_publish_data.get("task") or {}
    return {
        "id": sg_publish_data.get("id"),
        "name": sg_publish_data.get("name"),
        "code": sg_publish_data.get("code"),
        "version_number": sg_publish_data.get("version_number"),
        "entity_type": entity.get("type"),
        "entity_id": entity.get("id"),
        "entity_name": entity.get("name"),
        "task_id": task.get("id"),
        "path": path.replace("\\", "/"),
    }


def _require_file(path):
    if not os.path.exists(path):
        raise Exception("File not found on disk - '%s'" % path)


def _udim_files(path):
    import glob

    return glob.glob(path.replace(UDIM_TOKEN, "[0-9][0-9][0-9][0-9]"))
