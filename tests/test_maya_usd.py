"""
Headless check of the ShotGrid -> Maya slice. Run with mayapy:

    "C:\\Program Files\\Autodesk\\Maya2026\\bin\\mayapy.exe" tests\\test_maya_usd.py

It bootstraps tk-maya with this repo's config (using the sign-in saved by the
desktop app), then collects, validates and exports a USD from a test scene and
loads it back through the loader actions.

It only READS from ShotGrid: the publish itself is never registered.
"""

import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_CACHE = r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
CORE_PYTHON = os.path.join(BUNDLE_CACHE, "app_store", "tk-core", "v0.24.6", "python")
PROJECT_ID = int(os.environ.get("SG_TEST_PROJECT_ID", "91"))

os.environ["TK_BOOTSTRAP_CONFIG_OVERRIDE"] = os.path.join(REPO, "config")

import maya.standalone

maya.standalone.initialize()
import maya.cmds as cmds

sys.path.insert(0, CORE_PYTHON)
import sgtk


def check(label, condition):
    print("%s  %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        raise SystemExit(1)


user = sgtk.authentication.ShotgunAuthenticator().get_default_user()
check("saved desktop sign-in found", user is not None)

manager = sgtk.bootstrap.ToolkitManager(user)
manager.plugin_id = "basic.maya"
manager.base_configuration = "sgtk:descriptor:app_store?name=tk-config-basic"
manager.bundle_cache_fallback_paths = [BUNDLE_CACHE]
engine = manager.bootstrap_engine("tk-maya", entity={"type": "Project", "id": PROJECT_ID})

check("tk-maya engine started in %s" % engine.context, engine.name == "tk-maya")
config_path = engine.sgtk.configuration_descriptor.get_path()
check("config comes from this repo (%s)" % config_path, os.path.normcase(config_path) == os.path.normcase(os.path.join(REPO, "config")))
check("publisher and loader loaded", {"tk-multi-publish2", "tk-multi-loader2"} <= set(engine.apps))

# ---- a small test scene, saved with a version number
work_dir = tempfile.mkdtemp(prefix="sg_pipeline_test_")
cmds.file(new=True, force=True)
cube = cmds.polyCube(name="testCube")[0]
shader = cmds.shadingNode("standardSurface", asShader=True, name="testMtl")
sg_set = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="testMtlSG")
cmds.connectAttr(shader + ".outColor", sg_set + ".surfaceShader")
cmds.sets(cube, edit=True, forceElement=sg_set)
scene_path = os.path.join(work_dir, "testAsset_model_v003.ma")
cmds.file(rename=scene_path)
cmds.file(save=True, type="mayaAscii")

# ---- publisher: collect + validate (no publish)
publisher = engine.apps["tk-multi-publish2"]
pm = publisher.create_publish_manager()
pm.collect_session()
items = {item.type_spec: item for item in pm.tree}
print("     collected:", sorted(items))
check("USD item collected", "maya.session.usd" in items)

usd_item = items["maya.session.usd"]
usd_tasks = [t for t in usd_item.tasks if t.name == "Publish USD Geometry"]
check("USD publish plugin attached to the item", len(usd_tasks) == 1)
usd_task = usd_tasks[0]

failed = pm.validate()
check("validation passes (%d failures)" % len(failed), not failed)

expected = os.path.join(work_dir, "publish", "usd", "testAsset_model_v003.usd")
check("publish path is %s" % expected, os.path.normcase(usd_item.properties["path"]) == os.path.normcase(expected))
check("publish type is USD Geometry", usd_item.properties["publish_type"] == "USD Geometry")

hook = usd_task.plugin._hook_instance
check("publish version read from file name", hook.get_publish_version(usd_task.settings, usd_item) == 3)
print("     publish name:", hook.get_publish_name(usd_task.settings, usd_item))

# ---- export only (skips registering the publish in ShotGrid)
hook.export_usd(usd_item.properties["path"])
check("USD file written", os.path.exists(expected))

from pxr import Usd, UsdGeom, UsdShade

stage = Usd.Stage.Open(expected)
print("     prims:", [(str(p.GetPath()), p.GetTypeName()) for p in stage.Traverse()])
meshes = [p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
check("USD contains the mesh", [p.GetName() for p in meshes] == ["testCube"])
check("mesh has UVs", UsdGeom.PrimvarsAPI(meshes[0]).HasPrimvar("st"))
check("mesh has a material bound", bool(UsdShade.MaterialBindingAPI(meshes[0]).GetDirectBinding().GetMaterialPath()))

# ---- loader actions, with publish data shaped like a zero-config publish
loader = engine.apps["tk-multi-loader2"]
publish_data = {
    "type": "PublishedFile",
    "id": 0,
    "name": "testAsset_model.usd",
    "code": "testAsset_model_v003.usd",
    "entity": {"type": "Asset", "id": 0, "name": "testAsset"},
    "path": {
        "link_type": "web",
        "url": "file:///" + expected.replace("\\", "/"),
        "name": "testAsset_model_v003.usd",
    },
}
actions = loader.execute_hook_method(
    "actions_hook", "generate_actions",
    sg_publish_data=publish_data, actions=["usd_stage", "usd_import", "reference"], ui_area="main",
)
check("loader offers the USD actions", {"usd_stage", "usd_import"} <= {a["name"] for a in actions})

cmds.file(new=True, force=True)
loader.execute_hook_method("actions_hook", "execute_action", name="usd_stage", params=None, sg_publish_data=publish_data)
proxies = cmds.ls(type="mayaUsdProxyShape")
check("usd_stage created a proxy shape", len(proxies) == 1)
check("proxy points at the publish", os.path.normcase(os.path.normpath(cmds.getAttr(proxies[0] + ".filePath"))) == os.path.normcase(expected))

loader.execute_hook_method("actions_hook", "execute_action", name="usd_import", params=None, sg_publish_data=publish_data)
check("usd_import created Maya meshes", len(cmds.ls(type="mesh", noIntermediate=True)) == 1)

print("\nALL CHECKS PASSED")
engine.destroy()
maya.standalone.uninitialize()
