"""
Self-test that runs INSIDE Katana in script mode (see tests/run_katana_selftest.ps1).

It checks that the Arnold plug-in (KtoA) is loaded, that the Toolkit engine
starts, and runs the loader's "Create UsdIn Node" action on the newest USD
Geometry publish, then cooks the scene graph to see that geometry comes out of
it. Results go to a JSON file. It only reads from ShotGrid.
"""

import json
import os
import sys
import traceback

OUT = os.environ["SG_PIPELINE_SELFTEST_OUT"]
result = {"checks": {}, "error": None}
checks = result["checks"]


def write():
    result["passed"] = result["error"] is None and bool(checks) and all(checks.values())
    with open(OUT, "w") as handle:
        json.dump(result, handle, indent=2)


def locations(client, path, found, limit=400):
    """Walk the scene graph below path, collecting (path, type)."""
    data = client.cookLocation(path)
    type_attr = data.getAttrs().getChildByName("type") if data.getAttrs() else None
    found.append((path, type_attr.getValue() if type_attr else None))
    if len(found) >= limit:
        return
    children = data.getPotentialChildren()
    if hasattr(children, "getNearestSample"):
        children = children.getNearestSample(0)
    for child in children:
        locations(client, "%s/%s" % (path, child), found, limit)


def main():
    from Katana import Configuration, NodegraphAPI, RenderingAPI

    result["katana_version"] = Configuration.get("KATANA_RELEASE")
    result["ui_mode"] = bool(Configuration.get("KATANA_UI_MODE"))
    result["python"] = sys.version.split()[0]

    # ---- Arnold
    renderers = list(RenderingAPI.RenderPlugins.GetRendererPluginNames())
    result["renderers"] = renderers
    checks["arnold_renderer_plugin_loaded"] = "arnold" in renderers
    result["default_renderer"] = os.environ.get("DEFAULT_RENDERER")

    # ---- engine: started by the engine's Startup/init.py when Katana finished starting
    sgtk = sys.modules.get("sgtk")
    engine = sgtk.platform.current_engine() if sgtk else None
    checks["engine_running"] = engine is not None and engine.name == "tk-katana"
    if engine is None:
        raise RuntimeError("The tk-katana engine did not start (see Katana's log).")
    result["context"] = str(engine.context)
    result["apps"] = sorted(engine.apps)
    result["host_info"] = engine.host_info
    checks["loader_loaded"] = "tk-multi-loader2" in engine.apps

    loader = engine.apps["tk-multi-loader2"]
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
        "actions_hook", "generate_actions", sg_publish_data=publish,
        actions=loader.get_setting("action_mappings")["USD Geometry"], ui_area="main",
    )
    checks["usd_in_action_offered"] = [a["name"] for a in actions] == ["katana_usd_in"]

    loader.execute_hook_method(
        "actions_hook", "execute_action", name="katana_usd_in", params=None, sg_publish_data=publish,
    )
    nodes = [n for n in NodegraphAPI.GetRootNode().getChildren() if n.getType() == "UsdIn"]
    checks["usd_in_node_created"] = len(nodes) == 1
    node = nodes[0]
    result["node"] = node.getName()
    file_name = node.getParameter("fileName").getValue(0)
    result["file_name"] = file_name
    checks["node_points_at_the_published_file"] = os.path.exists(file_name)

    # ---- cook: does geometry come out of the node?
    from Katana import FnGeolib, Nodes3DAPI

    runtime = FnGeolib.GetRegisteredRuntimeInstance()
    transaction = runtime.createTransaction()
    client = transaction.createClient()
    op = Nodes3DAPI.GetOp(transaction, node)
    transaction.setClientOp(client, op)
    runtime.commit(transaction)

    found = []
    locations(client, "/root", found)
    result["location_count"] = len(found)
    meshes = [p for p, t in found if t in ("subdmesh", "polymesh")]
    result["meshes"] = meshes[:10]
    result["location_types"] = sorted({t for _, t in found if t})
    checks["scene_graph_has_mesh_locations"] = len(meshes) > 0

    checks["publish_id_stored_on_the_node"] = (
        node.getParameter("sgPublishId") is not None
        and int(node.getParameter("sgPublishId").getValue(0)) == publish["id"]
    )

    work = os.environ.get("SG_PIPELINE_KATANA_WORK")
    if work:
        publish_checks(engine, node, publish, work.replace("\\", "/"))


def publish_checks(engine, usd_in, source_publish, work):
    """
    Katana -> Nuke: build a small render scene around the UsdIn node, save it,
    and run the publisher on the frames a batch render wrote (the ps1 renders
    them when they are missing and runs this test again). Unless
    SG_PIPELINE_SELFTEST_PUBLISH is 1 nothing is registered in ShotGrid and
    the would-be publishes are written to the result instead
    (tests/test_nuke_usd.py loads them in Nuke).
    """
    from Katana import KatanaFile, NodegraphAPI

    root = NodegraphAPI.GetRootNode()
    camera = NodegraphAPI.CreateNode("CameraCreate", root)
    camera.getParameter("transform.translate.z").setValue(10.0, 0)
    merge = NodegraphAPI.CreateNode("Merge", root)
    for index, source in enumerate((usd_in, camera)):
        source.getOutputPortByIndex(0).connect(merge.addInputPort("i%d" % index))
    define = NodegraphAPI.CreateNode("RenderOutputDefine", root)
    define.getInputPortByIndex(0).connect(merge.getOutputPortByIndex(0))
    base = "args.renderSettings.outputs.outputName."
    define.getParameter(base + "locationType.enable").setValue(1, 0)
    define.getParameter(base + "locationType.value").setValue("file", 0)
    define.checkDynamicParameters()
    location = define.getParameter(base + "locationSettings.renderLocation")
    location.getChild("enable").setValue(1, 0)
    location.getChild("value").setExpression("'%s/renders/beauty.%%04d.exr' %% frame" % work)
    render = NodegraphAPI.CreateNode("Render", root)
    render.getInputPortByIndex(0).connect(define.getOutputPortByIndex(0))
    NodegraphAPI.SetInTime(1)
    NodegraphAPI.SetOutTime(2)

    scene = "%s/katana_test_v001.katana" % work
    KatanaFile.Save(scene)
    result["scene"] = scene
    result["render_node"] = render.getName()
    checks["scene_saved"] = os.path.exists(scene)

    checks["publisher_loaded"] = "tk-multi-publish2" in engine.apps
    manager = engine.apps["tk-multi-publish2"].create_publish_manager()
    manager.collect_session()
    sessions = [item for item in manager.tree if item.type_spec == "katana.session"]
    checks["project_item_collected"] = len(sessions) == 1
    items = [item for item in manager.tree if item.type_spec == "katana.render"]
    result["render_items"] = [item.name for item in items]
    result["frames_on_disk"] = [len(item.properties["sequence_paths"]) for item in items]
    if not items:
        # nothing rendered yet: the ps1 renders the saved scene and runs this again
        result["needs_render"] = True
        return
    checks["render_item_collected"] = len(items) == 1
    item = items[0]
    checks["sequence_path_uses_a_frame_token"] = item.properties["sequence_path"].endswith("beauty.%04d.exr")
    checks["both_frames_found"] = len(item.properties["sequence_paths"]) == 2
    checks["render_item_has_the_publish_plugin"] = [t.name for t in item.tasks] == ["Publish Render"]
    checks["render_links_to_the_usd_publish"] = item.properties["source_publish_ids"] == [source_publish["id"]]

    failed = manager.validate()
    result["publish_validation_failures"] = [str(f) for f in failed]
    checks["publish_validation_passes"] = not failed
    if failed:
        return
    result["publish_name"] = item.properties["publish_name"]
    result["publish_version"] = item.properties["publish_version"]
    checks["name_and_version_from_the_project_file"] = (
        item.properties["publish_name"] == "katana_test_Render_primary"
        and item.properties["publish_version"] == 1
    )

    if os.environ.get("SG_PIPELINE_SELFTEST_PUBLISH") == "1":
        for tree_item in manager.tree:
            tree_item.description = "sg_pipeline Katana self-test"
        manager.publish()
        manager.finalize()
        registered = engine.shotgun.find_one(
            "PublishedFile",
            [["id", "is", (item.properties.get("sg_publish_data") or {}).get("id") or 0]],
            ["code", "name", "version_number", "published_file_type", "upstream_published_files", "path"],
        )
        result["registered_publish"] = registered and {
            "id": registered["id"], "name": registered["name"], "version": registered["version_number"],
            "type": registered["published_file_type"]["name"],
            "upstream": [u["id"] for u in registered["upstream_published_files"] or []],
        }
        checks["render_registered"] = registered is not None
        checks["registered_render_links_to_the_usd_publish"] = bool(registered) and source_publish["id"] in [
            u["id"] for u in registered["upstream_published_files"] or []
        ]
        return

    from urllib.parse import quote

    path = item.properties["path"]
    result["render_publishes"] = [
        {
            "type": "PublishedFile",
            "id": 0,
            "name": item.properties["publish_name"],
            "code": os.path.basename(path),
            "version_number": item.properties["publish_version"],
            "published_file_type": {"type": "PublishedFileType", "name": item.properties["publish_type"]},
            "entity": source_publish.get("entity"),
            "path": {"link_type": "web", "url": "file:///" + quote(path.replace("\\", "/"), safe="/:"), "name": os.path.basename(path)},
            "frames": len(item.properties["sequence_paths"]),
        }
    ]

try:
    main()
except Exception:
    result["error"] = traceback.format_exc()
write()

try:
    _sgtk = sys.modules.get("sgtk")
    if _sgtk and _sgtk.platform.current_engine():
        _sgtk.platform.current_engine().destroy()
except Exception:
    pass
