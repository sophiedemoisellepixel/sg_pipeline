"""
Self-test that runs INSIDE Mari in terminal mode (see tests/run_mari_selftest.ps1).

With the Toolkit engine started by the startup script it:
  1. runs the loader's "Create Mari Project" action on the newest USD Geometry
     publish of the project,
  2. runs "Import as Layer" on the textures the Painter self-test exported
     (read from its result file),
and writes what Mari ended up with to a JSON file. The temporary Mari project
is closed without saving and removed. It only reads from ShotGrid.
"""

import json
import os
import struct
import sys
import traceback

import mari

OUT = os.environ["SG_PIPELINE_SELFTEST_OUT"]
PAINTER_RESULT = os.environ.get("SG_PIPELINE_PAINTER_RESULT")

result = {"checks": {}, "error": None}
checks = result["checks"]


def png_size(path):
    with open(path, "rb") as handle:
        header = handle.read(24)
    return struct.unpack(">II", header[16:24])


def main():
    result["mari_version"] = mari.app.version().string()
    result["terminal_mode"] = mari.app.inTerminalMode()

    sgtk = sys.modules.get("sgtk")
    engine = sgtk.platform.current_engine() if sgtk else None
    checks["engine_started_by_startup_script"] = engine is not None and engine.name == "tk-mari"
    if engine is None:
        raise RuntimeError("The tk-mari engine is not running (see Mari's log).")
    result["context"] = str(engine.context)
    result["apps"] = sorted(engine.apps)
    checks["loader_loaded"] = "tk-multi-loader2" in engine.apps

    loader = engine.apps["tk-multi-loader2"]
    mappings = loader.get_setting("action_mappings")

    # ---- 1. project from the published USD
    publish = engine.shotgun.find_one(
        "PublishedFile",
        [["project", "is", engine.context.project],
         ["published_file_type.PublishedFileType.code", "is", "USD Geometry"],
         ["sg_status_list", "is_not", None]],
        ["code", "name", "version_number", "published_file_type", "entity", "task", "path"],
        order=[{"field_name": "id", "direction": "desc"}],
    )
    if publish is None:
        raise RuntimeError("No USD Geometry publish found in the project.")
    result["publish"] = {"id": publish["id"], "code": publish["code"]}

    actions = loader.execute_hook_method(
        "actions_hook", "generate_actions",
        sg_publish_data=publish, actions=mappings["USD Geometry"], ui_area="main",
    )
    checks["geometry_actions_offered"] = [a["name"] for a in actions] == ["mari_new_project", "mari_add_geometry"]

    loader.execute_hook_method(
        "actions_hook", "execute_action",
        name="mari_new_project", params=None, sg_publish_data=publish,
    )
    project = mari.projects.current()
    checks["project_created"] = project is not None
    result["project_name"] = project.name()
    result["project_uuid"] = project.uuid()
    result["objects"] = [g.name() for g in mari.geo.list()]
    geo = mari.geo.current()
    result["patches"] = [p.udim() for p in geo.patchList()]
    result["channels_after_create"] = [c.name() for c in geo.channelList()]
    checks["mesh_loaded_with_uv_patches"] = len(result["objects"]) >= 1 and 1001 in result["patches"]
    metadata = json.loads(project.metadata("sg_pipeline_source_publish"))
    checks["source_publish_in_metadata"] = metadata["id"] == publish["id"]

    # ---- 2. textures exported by Painter, as layers
    if os.environ.get("SG_PIPELINE_USE_SITE_TEXTURES") == "1":
        # the real Texture publishes registered in ShotGrid
        texture_publishes = engine.shotgun.find(
            "PublishedFile",
            [["project", "is", engine.context.project],
             ["published_file_type.PublishedFileType.code", "is", "Texture"],
             ["sg_status_list", "is_not", None]],
            ["code", "name", "version_number", "published_file_type", "entity", "task", "path",
             "upstream_published_files"],
            order=[{"field_name": "id", "direction": "asc"}],
        )
        for texture in texture_publishes:
            resolved = sgtk.util.resolve_publish_path(engine.sgtk, texture)
            texture["files"] = [resolved.replace("<UDIM>", "1001")]
        result["site_texture_publishes"] = [
            {"id": t["id"], "name": t["name"], "version": t["version_number"],
             "upstream": [u["id"] for u in t.get("upstream_published_files") or []]}
            for t in texture_publishes
        ]
        checks["textures_link_back_to_the_usd_publish"] = bool(texture_publishes) and all(
            publish["id"] in [u["id"] for u in t.get("upstream_published_files") or []]
            for t in texture_publishes
        )
    elif PAINTER_RESULT and os.path.exists(PAINTER_RESULT):
        with open(PAINTER_RESULT) as handle:
            texture_publishes = json.load(handle).get("texture_publishes", [])
    else:
        texture_publishes = []
    checks["painter_textures_available"] = len(texture_publishes) > 0

    # shape the path like a real zero-config publish: a file:// url
    for texture in texture_publishes:
        local_path = texture["path"].get("local_path")
        if local_path and "local_storage" not in texture["path"]:
            texture["path"] = {
                "link_type": "web",
                "url": "file:///" + local_path.replace("\\", "/"),
                "name": texture["code"],
            }

    imported = []
    for texture in texture_publishes:
        actions = loader.execute_hook_method(
            "actions_hook", "generate_actions",
            sg_publish_data=texture, actions=mappings["Texture"], ui_area="main",
        )
        assert [a["name"] for a in actions] == ["mari_import_layer"], actions
        loader.execute_hook_method(
            "actions_hook", "execute_action",
            name="mari_import_layer", params=None, sg_publish_data=texture,
        )
        map_name = texture["name"].rsplit("_", 1)[-1]
        channel = geo.findChannel(map_name)
        layer_name = "%s_v%03d" % (texture["name"], texture["version_number"])
        layer = channel.findLayer(layer_name) if channel else None
        image = layer.imageSet().imageList()[0] if layer else None
        imported.append(
            {
                "channel": map_name,
                "layer": layer.name() if layer else None,
                "mari_size": [image.width(), image.height()] if image else None,
                "file_size": list(png_size(texture["files"][0])),
            }
        )
    result["imported"] = imported
    checks["every_map_has_its_channel_and_layer"] = bool(imported) and all(i["layer"] for i in imported)
    checks["patches_resized_to_the_textures"] = bool(imported) and all(
        i["mari_size"] == i["file_size"] for i in imported
    )
    result["channels_after_import"] = [c.name() for c in geo.channelList()]

    # the base colour Painter exported was a flat red fill: read a pixel back
    base = next((t for t in texture_publishes if t["name"].endswith("_basecolor")), None)
    if base:
        layer = geo.findChannel("basecolor").findLayer("%s_v%03d" % (base["name"], base["version_number"]))
        # export the layer again and compare a pixel with Painter's file
        import tempfile

        from PySide2 import QtGui

        export_dir = tempfile.mkdtemp(prefix="sg_pipeline_mari_")
        layer.exportImages(os.path.join(export_dir, "roundtrip.$UDIM.png").replace("\\", "/"))

        def center_pixel(path):
            image = QtGui.QImage(path)
            color = QtGui.QColor(image.pixel(image.width() // 2, image.height() // 2))
            return [color.red(), color.green(), color.blue()]

        source = center_pixel(base["files"][0])
        roundtrip = center_pixel(os.path.join(export_dir, "roundtrip.1001.png"))
        result["basecolor_pixel"] = {"painter_file": source, "mari_layer": roundtrip}
        checks["basecolor_is_the_red_fill"] = source[0] > 128 and source[1] < 128 and source[2] < 128
        checks["mari_layer_matches_painter_file"] = all(abs(a - b) <= 2 for a, b in zip(source, roundtrip))


def publish_checks():
    """
    Mari -> Maya: collect, validate and export every channel through the
    publisher. Unless SG_PIPELINE_SELFTEST_PUBLISH is 1 the ShotGrid
    registration is skipped and the would-be publishes are written to the
    result instead (tests/test_maya_textures.py loads them in Maya).
    """
    sgtk = sys.modules["sgtk"]
    engine = sgtk.platform.current_engine()
    checks["publisher_loaded"] = "tk-multi-publish2" in engine.apps

    manager = engine.apps["tk-multi-publish2"].create_publish_manager()
    manager.collect_session()
    items = [item for item in manager.tree if item.type_spec == "mari.channel"]
    result["channel_items"] = [item.name for item in items]
    checks["channel_items_collected"] = len(items) > 0
    checks["every_channel_item_has_the_publish_plugin"] = all(
        [t.name for t in item.tasks] == ["Publish Channel"] for item in items
    )

    failed = manager.validate()
    result["publish_validation_failures"] = [str(f) for f in failed]
    checks["publish_validation_passes"] = not failed
    if failed:
        return

    source_id = json.loads(mari.projects.current().metadata("sg_pipeline_source_publish"))["id"]

    if os.environ.get("SG_PIPELINE_SELFTEST_PUBLISH") == "1":
        for item in manager.tree:
            item.description = "sg_pipeline Mari self-test"
        manager.publish()
        manager.finalize()
        ids = [(item.properties.get("sg_publish_data") or {}).get("id") for item in items]
        registered = engine.shotgun.find(
            "PublishedFile", [["id", "in", [i for i in ids if i]]],
            ["code", "name", "version_number", "upstream_published_files"],
        )
        result["registered_publishes"] = [
            {"id": p["id"], "name": p["name"], "version": p["version_number"],
             "upstream": [u["id"] for u in p["upstream_published_files"] or []]}
            for p in registered
        ]
        checks["all_channels_registered"] = len(registered) == len(items) > 0
        checks["channels_link_back_to_the_mesh_publish"] = bool(registered) and all(
            source_id in [u["id"] for u in p["upstream_published_files"] or []] for p in registered
        )
        checks["registered_files_exist"] = all(
            item.properties.get("exported_files") for item in items
        )
        return

    would_publish = []
    for item in items:
        hook = item.tasks[0].plugin._hook_instance
        files = hook.export_channel(item)
        would_publish.append(
            {
                "type": "PublishedFile",
                "id": 0,
                "name": item.properties["publish_name"],
                "code": os.path.basename(item.properties["path"]),
                "version_number": item.properties["publish_version"],
                "published_file_type": {"type": "PublishedFileType", "name": item.properties["publish_type"]},
                "entity": {"type": "Asset", "id": 0, "name": "testAsset"},
                "path": {
                    "link_type": "web",
                    "url": "file:///" + item.properties["path"].replace("\\", "/"),
                    "name": os.path.basename(item.properties["path"]),
                },
                "files": files,
            }
        )
    result["texture_publishes"] = would_publish
    checks["channels_exported"] = bool(would_publish) and all(
        p["files"] and all(os.path.exists(f) for f in p["files"]) for p in would_publish
    )
    checks["publish_names_drop_the_mesh_version"] = all(
        not any(part.startswith("v0") for part in p["name"].split("_")) for p in would_publish
    )


try:
    main()
    if os.environ.get("SG_PIPELINE_MARI_EXPORT_ROOT"):
        publish_checks()
except Exception:
    result["error"] = traceback.format_exc()

# leave nothing behind: close without saving and remove the temporary project
try:
    uuid = result.get("project_uuid")
    if mari.projects.current() is not None:
        mari.projects.close(False)
    if uuid:
        mari.projects.remove(uuid)
        result["cleanup"] = "project removed"
except Exception:
    result["cleanup"] = traceback.format_exc()

result["passed"] = result["error"] is None and all(checks.values())
with open(OUT, "w") as handle:
    json.dump(result, handle, indent=2)

# shut the engine down and make sure Mari exits
try:
    _sgtk = sys.modules.get("sgtk")
    if _sgtk and _sgtk.platform.current_engine():
        _sgtk.platform.current_engine().destroy()
finally:
    mari.app.quit()
