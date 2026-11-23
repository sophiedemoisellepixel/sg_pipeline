"""
Exports one Mari channel, flattened, and publishes it to ShotGrid.

    hook: "{self}/publish_file.py:{config}/tk-multi-publish2/mari/publish_channel.py"

Mari projects are not files, so there is no project folder to export next to.
The textures go under an export root instead, one file per UDIM tile:

    <export root>/<entity>/<mari project>/v###/<object>_<channel>.<UDIM>.<ext>

The export root is the "Export Root" setting, else the SG_PIPELINE_MARI_EXPORT_ROOT
environment variable, else <home>/Documents/Mari/sg_pipeline_publish.

Each channel is registered as one "Texture" publish named "<object>_<channel>"
(the object's own version suffix is dropped so the name stays the same when the
mesh is updated). The version is one more than the newest publish of that name
on the same entity. 8-bit channels are written as PNG, deeper ones as EXR.

If the project was created from a published mesh (see the loader's "Create
Mari Project" action) that mesh is recorded as what the textures were made from.
"""

import glob
import json
import os
import re

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

PUBLISH_TYPE = "Texture"
UDIM_TOKEN = "<UDIM>"
SOURCE_PUBLISH_METADATA = "sg_pipeline_source_publish"
EXPORT_ROOT_ENV = "SG_PIPELINE_MARI_EXPORT_ROOT"


class MariChannelPublishPlugin(HookBaseClass):
    @property
    def description(self):
        return """
        <p>Exports this channel flattened, one file per UDIM tile, and
        publishes it to Flow Production Tracking as one <b>Texture</b>.</p>
        """

    @property
    def settings(self):
        plugin_settings = super().settings or {}
        plugin_settings["Export Root"] = {
            "type": "str",
            "default": "",
            "description": "Folder the textures are exported under. Empty: use "
            "the %s environment variable, else Documents/Mari/sg_pipeline_publish."
            % EXPORT_ROOT_ENV,
        }
        return plugin_settings

    @property
    def item_filters(self):
        return ["mari.channel"]

    def accept(self, settings, item):
        return {"accepted": True, "checked": True}

    def validate(self, settings, item):
        import mari

        project = mari.projects.current()
        if project is None:
            raise Exception("There is no Mari project open.")
        channel = self._channel(item)

        publish_name = "%s_%s" % (
            strip_version(item.properties["geo_name"]),
            item.properties["channel_name"],
        )
        version = self._next_version(item, publish_name)
        extension = "png" if channel.depth() == 8 else "exr"

        # the studio location for the task
        # (<step>/publish/textures/<mari project>/v###/<name>.<UDIM>.<ext>),
        # else the export root (no Asset task, or a template missing)
        publish_path = load_paths_helper(self.disk_location).mari_texture_path(
            self.parent.sgtk, item.context, project.name(), _safe(publish_name), version, extension
        )
        if not publish_path:
            entity = item.context.entity or item.context.project
            export_dir = os.path.join(
                export_root(settings["Export Root"].value),
                _safe(entity["name"]),
                _safe(project.name()),
                "v%03d" % version,
            )
            publish_path = os.path.join(
                export_dir, "%s.%s.%s" % (_safe(publish_name), UDIM_TOKEN, extension)
            )
            self.logger.info("Not in an Asset task; exporting under the export root.")

        item.properties["path"] = publish_path
        item.properties["publish_path"] = publish_path
        item.properties["publish_type"] = PUBLISH_TYPE
        item.properties["publish_name"] = publish_name
        item.properties["publish_version"] = version

        self.logger.info("Channel will be exported to: %s" % publish_path)
        return super().validate(settings, item)

    def publish(self, settings, item):
        files = self.export_channel(item)
        item.properties["exported_files"] = files

        # The mesh these textures were painted on, linked by id: with no storage
        # roots configured, ShotGrid cannot find a publish by its path.
        source = source_publish()
        if source and source.get("id"):
            item.properties["publish_kwargs"] = {"dependency_ids": [source["id"]]}

        super().publish(settings, item)

    def export_channel(self, item):
        """Write the flattened channel to the item's publish path. Returns the files."""
        publish_path = item.properties["path"]
        self.parent.ensure_folder_exists(os.path.dirname(publish_path))

        template = publish_path.replace("\\", "/").replace(UDIM_TOKEN, "$UDIM")
        self._channel(item).exportImagesFlattened(template)

        files = sorted(glob.glob(publish_path.replace(UDIM_TOKEN, "[0-9][0-9][0-9][0-9]")))
        if not files:
            raise Exception("Mari did not export any file for %s" % item.name)
        self.logger.info("Exported %d file(s) for %s" % (len(files), item.name))
        return files

    def _channel(self, item):
        import mari

        geo = next(
            (g for g in mari.geo.list() if g.name() == item.properties["geo_name"]), None
        )
        channel = geo.findChannel(item.properties["channel_name"]) if geo else None
        if channel is None:
            raise Exception(
                "Channel '%s' no longer exists on '%s'."
                % (item.properties["channel_name"], item.properties["geo_name"])
            )
        return channel

    def _next_version(self, item, publish_name):
        """One more than the newest publish of this name on the item's entity."""
        context = item.context
        filters = [
            ["project", "is", context.project],
            ["name", "is", publish_name],
            ["published_file_type.PublishedFileType.code", "is", PUBLISH_TYPE],
        ]
        if context.entity:
            filters.append(["entity", "is", context.entity])
        latest = self.parent.shotgun.find_one(
            "PublishedFile",
            filters,
            ["version_number"],
            order=[{"field_name": "version_number", "direction": "desc"}],
        )
        return ((latest or {}).get("version_number") or 0) + 1


def load_paths_helper(hook_folder):
    """config/hooks/lib/sg_pipeline_templates.py (hooks are loaded by path, not as a package)."""
    import importlib.util

    path = os.path.join(os.path.dirname(os.path.dirname(hook_folder)), "lib", "sg_pipeline_templates.py")
    spec = importlib.util.spec_from_file_location("sg_pipeline_templates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def export_root(setting_value):
    root = setting_value or os.environ.get(EXPORT_ROOT_ENV)
    if not root:
        root = os.path.join(os.path.expanduser("~"), "Documents", "Mari", "sg_pipeline_publish")
    return os.path.normpath(os.path.expandvars(os.path.expanduser(root)))


def strip_version(name):
    """testAsset_model_v003 -> testAsset_model"""
    return re.sub(r"[._-]v\d+$", "", name)


def source_publish():
    """The publish the project's mesh came from, or None."""
    import mari

    project = mari.projects.current()
    if project is None or not project.hasMetadata(SOURCE_PUBLISH_METADATA):
        return None
    try:
        return json.loads(project.metadata(SOURCE_PUBLISH_METADATA))
    except Exception:
        return None


def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)
