"""
Publishes the frames a Katana Render node wrote to disk (Katana -> Nuke).

    hook: "{self}/publish_file.py:{config}/tk-multi-publish2/katana/publish_render.py"

The files are published where they are. Each output becomes one "Rendered
Image" publish whose path is the sequence (e.g. beauty.%04d.exr), which Nuke's
loader turns into a Read node with the right frame range.

    name     <katana project without version>_<render node>_<output>
    version  the v### of the Katana project file, else one more than the
             newest publish of that name on the same entity

The publishes the loader brought into the project (UsdIn nodes) are recorded
as what the render was made from.
"""

import os
import re

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

PUBLISH_TYPE = "Rendered Image"


class KatanaRenderPublishPlugin(HookBaseClass):
    @property
    def description(self):
        return """
        <p>Publishes the frames this Render node output wrote to disk to Flow
        Production Tracking as one <b>Rendered Image</b>. The files are not
        copied or moved.</p>
        """

    @property
    def item_filters(self):
        return ["katana.render"]

    def accept(self, settings, item):
        return {"accepted": True, "checked": True}

    def validate(self, settings, item):
        frames = [f for f in item.properties["sequence_paths"] if os.path.exists(f)]
        if not frames:
            raise Exception("No rendered frames on disk for %s." % item.name)

        project_path = item.parent.properties.get("path") or ""
        project_name = os.path.splitext(os.path.basename(project_path))[0] or "untitled"
        publish_name = "%s_%s_%s" % (
            strip_version(project_name),
            _safe(item.properties["render_node"]),
            _safe(item.properties["output_name"]),
        )
        version_match = re.search(r"[._-]v(\d+)$", project_name)
        version = int(version_match.group(1)) if version_match else self._next_version(item, publish_name)

        item.properties["path"] = item.properties["sequence_path"]
        item.properties["publish_path"] = item.properties["sequence_path"]
        item.properties["publish_type"] = PUBLISH_TYPE
        item.properties["publish_name"] = publish_name
        item.properties["publish_version"] = version

        self.logger.info(
            "%d frame(s) will be published as %s v%03d" % (len(frames), publish_name, version)
        )
        return super().validate(settings, item)

    def publish(self, settings, item):
        # Linked by id: with no storage roots configured, ShotGrid cannot find
        # a publish by its path.
        source_ids = item.properties.get("source_publish_ids") or []
        if source_ids:
            item.properties["publish_kwargs"] = {"dependency_ids": list(source_ids)}
        super().publish(settings, item)

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


def strip_version(name):
    """katana_test_v001 -> katana_test"""
    return re.sub(r"[._-]v\d+$", "", name)


def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)
