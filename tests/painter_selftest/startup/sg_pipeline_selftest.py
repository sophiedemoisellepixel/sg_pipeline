"""
Self-test that runs INSIDE Substance 3D Painter (see tests/run_painter_selftest.ps1).

Only active when SG_PIPELINE_SELFTEST_OUT is set. Once the Toolkit engine is up
it runs the loader's "Create Painter Project" action on the newest USD Geometry
publish of the project, records what Painter ended up with in a JSON file, and
closes Painter. It only reads from ShotGrid.
"""

import json
import os
import sys
import time
import traceback

OUT = os.environ.get("SG_PIPELINE_SELFTEST_OUT")
TIMEOUT = 240

_timer = None
_state = {"step": "wait_engine", "started": time.time(), "result": {"checks": {}}}


def start_plugin():
    global _timer
    if not OUT:
        return
    from PySide6 import QtCore

    _timer = QtCore.QTimer()
    _timer.setInterval(1000)
    _timer.timeout.connect(_tick)
    _timer.start()


def close_plugin():
    global _timer
    if _timer is not None:
        _timer.stop()
        _timer = None


def _tick():
    try:
        if time.time() - _state["started"] > TIMEOUT:
            return _finish("timed out in step '%s'" % _state["step"])
        if _state["step"] == "wait_engine":
            _wait_engine()
        elif _state["step"] == "wait_project":
            _wait_project()
        elif _state["step"] == "wait_idle":
            _wait_idle()
    except Exception:
        _finish(traceback.format_exc())


def _wait_engine():
    sgtk = sys.modules.get("sgtk")
    engine = sgtk.platform.current_engine() if sgtk else None
    if engine is None:
        return

    import substance_painter.application
    import substance_painter.ui

    result = _state["result"]
    result["painter_version"] = substance_painter.application.version()
    result["context"] = str(engine.context)
    result["apps"] = sorted(engine.apps)

    from PySide6 import QtWidgets

    main_window = substance_painter.ui.get_main_window()
    menus = {m.title(): m for m in main_window.findChildren(QtWidgets.QMenu)}
    result["menus"] = sorted(t for t in menus if t)
    sg_menu = menus.get("Flow Production Tracking")
    result["sg_menu_items"] = [a.text() for a in sg_menu.actions() if not a.isSeparator()] if sg_menu else []
    result["checks"]["menu_added"] = sg_menu is not None
    result["checks"]["menu_has_loader"] = "Load..." in result["sg_menu_items"]

    publish = engine.shotgun.find_one(
        "PublishedFile",
        [["project", "is", engine.context.project],
         ["published_file_type.PublishedFileType.code", "is", "USD Geometry"],
         ["sg_status_list", "is_not", None]],
        ["code", "name", "version_number", "published_file_type", "entity", "task", "path"],
        order=[{"field_name": "id", "direction": "desc"}],
    )
    if publish is None:
        return _finish("no USD Geometry publish found in the project")
    result["publish"] = {"id": publish["id"], "code": publish["code"]}
    _state["publish"] = publish

    loader = engine.apps["tk-multi-loader2"]
    loader.execute_hook_method(
        "actions_hook", "execute_action",
        name="painter_new_project", params=None, sg_publish_data=publish,
    )
    _state["step"] = "wait_project"


def _wait_project():
    import substance_painter.project as sp_project
    import substance_painter.textureset

    if not sp_project.is_open() or not sp_project.is_in_edition_state() or sp_project.is_busy():
        return

    result = _state["result"]
    checks = result["checks"]
    publish = _state["publish"]

    result["mesh_path"] = sp_project.last_imported_mesh_path()
    result["texture_sets"] = [ts.name() for ts in substance_painter.textureset.all_texture_sets()]
    try:
        result["metadata"] = sp_project.Metadata("sg_pipeline").get("source_publish")
    except Exception:
        result["metadata"] = None

    checks["project_open"] = True
    checks["mesh_is_the_publish"] = os.path.basename(result["mesh_path"]) == publish["code"]
    checks["has_texture_sets"] = len(result["texture_sets"]) > 0
    checks["metadata_stored"] = bool(result["metadata"]) and result["metadata"].get("id") == publish["id"]

    if not os.environ.get("SG_PIPELINE_SELFTEST_WORK"):
        return _finish(None)

    # paint something, then let Painter finish computing before saving
    _add_fill_layers(result)
    _state["idle_ticks"] = 0
    _state["step"] = "wait_idle"


def _add_fill_layers(result):
    """Something to export: a red fill layer on every texture set."""
    import substance_painter.textureset as sp_textureset

    try:
        import substance_painter.colormanagement as sp_color
        import substance_painter.layerstack as sp_layerstack

        for texture_set in sp_textureset.all_texture_sets():
            position = sp_layerstack.InsertPosition.from_textureset_stack(texture_set.get_stack())
            fill = sp_layerstack.insert_fill(position)
            fill.set_source(sp_textureset.ChannelType.BaseColor, sp_color.Color(0.8, 0.1, 0.1))
        result["fill_layer"] = "added"
    except Exception:
        result["fill_layer"] = traceback.format_exc()


def _wait_idle():
    """Continue only once Painter has been idle for a few seconds in a row."""
    import substance_painter.project as sp_project

    if sp_project.is_busy() or not sp_project.is_in_edition_state():
        _state["idle_ticks"] = 0
        return
    _state["idle_ticks"] += 1
    if _state["idle_ticks"] < 3:
        return

    _state["step"] = "publishing"
    _texture_publish_checks(_state["result"], _state["result"]["checks"])
    _finish(None)


def _texture_publish_checks(result, checks):
    """
    Painter -> Mari: save the project, paint something, then collect, validate
    and export the textures through the publisher. The ShotGrid registration
    step is skipped; the would-be publishes are written to the result instead.
    """
    import sgtk
    import substance_painter.export as sp_export
    import substance_painter.project as sp_project
    import substance_painter.textureset as sp_textureset

    engine = sgtk.platform.current_engine()
    work_root = os.environ.get("SG_PIPELINE_SELFTEST_WORK")
    if not work_root:
        return

    if os.environ.get("SG_PIPELINE_SELFTEST_STUDIO") == "1":
        # saved the way Workfiles saves it: <step>/work/substancepainter/selftest.v###.spp
        tk = engine.sgtk
        template = tk.templates["substancepainter_asset_work"]
        target = engine.context.task or engine.context.entity
        tk.create_filesystem_structure(target["type"], target["id"], engine="tk-substancepainter")
        fields = engine.context.as_template_fields(template)
        fields.update(name="selftest", version=1)
        while os.path.exists(template.apply_fields(fields)):
            fields["version"] += 1
        project_path = template.apply_fields(fields)
        version = fields["version"]
        os.makedirs(os.path.dirname(project_path), exist_ok=True)
        result["expected_texture_folder"] = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(project_path))),
            "publish", "textures", "selftest", "v%03d" % fields["version"],
        )
    else:
        # a saved project with a version number in its name
        os.makedirs(work_root, exist_ok=True)
        version = 1
        while os.path.exists(os.path.join(work_root, "testAsset_texture_v%03d.spp" % version)):
            version += 1
        project_path = os.path.join(work_root, "testAsset_texture_v%03d.spp" % version)

    sp_project.save_as(project_path)
    result["project_path"] = sp_project.file_path()
    checks["project_saved"] = os.path.exists(project_path)

    publisher = engine.apps["tk-multi-publish2"]
    manager = publisher.create_publish_manager()
    manager.collect_session()
    items = [item for item in manager.tree if item.type_spec == "substancepainter.textures"]
    result["texture_items"] = [item.name for item in items]
    checks["texture_items_collected"] = len(items) > 0
    checks["every_texture_item_has_the_publish_plugin"] = all(
        [t.name for t in item.tasks] == ["Publish Textures"] for item in items
    )

    failed = manager.validate()
    result["validation_failures"] = [str(f) for f in failed]
    checks["validation_passes"] = not failed

    if os.environ.get("SG_PIPELINE_SELFTEST_PUBLISH") == "1" and not failed:
        # the real thing: export and register every texture in ShotGrid
        for item in manager.tree:
            item.description = "sg_pipeline Painter self-test"
        manager.publish()
        manager.finalize()
        registered = []
        for item in items:
            sg_publish = item.properties.get("sg_publish_data") or {}
            registered.append(
                {
                    "id": sg_publish.get("id"),
                    "name": item.properties["publish_name"],
                    "version_number": item.properties["publish_version"],
                    "path": item.properties["path"],
                    "files": item.properties.get("exported_files", []),
                }
            )
        result["registered_publishes"] = registered
        checks["all_textures_registered"] = bool(registered) and all(p["id"] for p in registered)
        linked = engine.shotgun.find(
            "PublishedFile",
            [["id", "in", [p["id"] for p in registered if p["id"]]]],
            ["upstream_published_files"],
        )
        source_id = (result.get("metadata") or {}).get("id")
        checks["textures_link_back_to_the_mesh_publish"] = bool(linked) and all(
            source_id in [u["id"] for u in p["upstream_published_files"] or []] for p in linked
        )
        checks["registered_files_exist"] = all(
            p["files"] and all(os.path.exists(f) for f in p["files"]) for p in registered
        )
        return

    would_publish = []
    for item in items:
        export = sp_export.export_project_textures(item.properties["export_config"])
        files = [path for paths in export.textures.values() for path in paths]
        would_publish.append(
            {
                "type": "PublishedFile",
                "id": 0,
                "name": item.properties["publish_name"],
                "code": os.path.basename(item.properties["path"]),
                "version_number": item.properties["publish_version"],
                "published_file_type": {"type": "PublishedFileType", "name": item.properties["publish_type"]},
                "entity": {"type": "Asset", "id": 0, "name": "testAsset"},
                "path": {"link_type": "local", "local_path": item.properties["path"]},
                "files": files,
                "status": str(export.status),
            }
        )
    result["texture_publishes"] = would_publish
    checks["textures_exported"] = bool(would_publish) and all(
        p["files"] and all(os.path.exists(f) for f in p["files"]) for p in would_publish
    )
    checks["files_match_publish_path"] = all(
        os.path.normcase(os.path.normpath(f))
        == os.path.normcase(os.path.normpath(p["path"]["local_path"].replace("<UDIM>", "1001")))
        for p in would_publish for f in p["files"][:1]
    )
    checks["version_from_project_name"] = all(p["version_number"] == version for p in would_publish)
    if result.get("expected_texture_folder"):
        # saved with the studio template: textures go to <step>/publish/textures/<name>/v###
        checks["textures_in_studio_folder"] = all(
            os.path.normcase(os.path.dirname(p["path"]["local_path"]))
            == os.path.normcase(result["expected_texture_folder"])
            for p in would_publish
        )


def _finish(error):
    import substance_painter.application
    import substance_painter.project as sp_project

    if _timer is not None:
        _timer.stop()
    result = _state["result"]
    result["error"] = error
    result["passed"] = error is None and all(result["checks"].values())
    with open(OUT, "w") as handle:
        json.dump(result, handle, indent=2)

    try:
        if sp_project.is_open():
            sp_project.close()
    finally:
        substance_painter.application.close()
