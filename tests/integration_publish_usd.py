"""
End-to-end check that WRITES to ShotGrid. Run with mayapy:

    "C:\\Program Files\\Autodesk\\Maya2026\\bin\\mayapy.exe" tests\\integration_publish_usd.py

In the test project it:
  1. finds or creates Asset "testAsset" with a "Model" Task,
  2. starts tk-maya in that Task's context,
  3. saves a small scene and publishes its geometry as USD Geometry
     (only the USD publish is run, the Maya scene itself is not published),
  4. loads the registered publish back through the loader.
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_CACHE = r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
CORE_PYTHON = os.path.join(BUNDLE_CACHE, "app_store", "tk-core", "v0.24.6", "python")
PROJECT_ID = int(os.environ.get("SG_TEST_PROJECT_ID", "91"))
WORK_ROOT = os.environ.get(
    "SG_TEST_WORK_ROOT", os.path.join(os.path.dirname(REPO), "sg_pipeline_work")
)
ASSET_NAME = "testAsset"
TASK_NAME = "Model"

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
sg = user.create_sg_connection()
project = {"type": "Project", "id": PROJECT_ID}

# ---- 1. Asset + Task (created only if missing)
asset = sg.find_one("Asset", [["project", "is", project], ["code", "is", ASSET_NAME]], ["code"])
if asset is None:
    asset = sg.create("Asset", {"project": project, "code": ASSET_NAME, "description": "sg_pipeline integration test"})
    print("     created Asset id %s" % asset["id"])
task = sg.find_one("Task", [["entity", "is", asset], ["content", "is", TASK_NAME]], ["content", "step"])
if task is None:
    data = {"project": project, "entity": asset, "content": TASK_NAME}
    step = sg.find_one("Step", [["entity_type", "is", "Asset"], ["code", "is", "Model"]], ["code"])
    if step:
        data["step"] = step
    task = sg.create("Task", data)
    print("     created Task id %s" % task["id"])
check("Asset %s (id %s) with Task %s (id %s)" % (ASSET_NAME, asset["id"], TASK_NAME, task["id"]), True)

# ---- 2. tk-maya in the task context
manager = sgtk.bootstrap.ToolkitManager(user)
manager.plugin_id = "basic.maya"
manager.base_configuration = "sgtk:descriptor:app_store?name=tk-config-basic"
manager.bundle_cache_fallback_paths = [BUNDLE_CACHE]
engine = manager.bootstrap_engine("tk-maya", entity={"type": "Task", "id": task["id"]})
check("engine context is the task (%s)" % engine.context, (engine.context.task or {}).get("id") == task["id"])
print("     environment:", engine.environment["name"])

# ---- 3. scene, next free version, USD publish only
scene_dir = os.path.join(WORK_ROOT, ASSET_NAME, "model")
os.makedirs(scene_dir, exist_ok=True)
version = 1
while os.path.exists(os.path.join(scene_dir, "%s_model_v%03d.ma" % (ASSET_NAME, version))):
    version += 1
scene_path = os.path.join(scene_dir, "%s_model_v%03d.ma" % (ASSET_NAME, version))

cmds.file(new=True, force=True)
cube = cmds.polyCube(name="testCube")[0]
shader = cmds.shadingNode("standardSurface", asShader=True, name="testMtl")
sg_set = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="testMtlSG")
cmds.connectAttr(shader + ".outColor", sg_set + ".surfaceShader")
cmds.sets(cube, edit=True, forceElement=sg_set)
cmds.file(rename=scene_path)
cmds.file(save=True, type="mayaAscii")

publisher = engine.apps["tk-multi-publish2"]
pm = publisher.create_publish_manager()
pm.collect_session()
usd_item = None
for item in pm.tree:
    item.description = "sg_pipeline integration test"
    for t in item.tasks:
        t.active = item.type_spec == "maya.session.usd" and t.name == "Publish USD Geometry"
    if item.type_spec == "maya.session.usd":
        usd_item = item
check("USD item collected", usd_item is not None)

failed = pm.validate()
check("validation passes", not failed)
pm.publish()
pm.finalize()

usd_path = usd_item.properties["path"]
check("USD file written: %s" % usd_path, os.path.exists(usd_path))

publish = usd_item.properties.get("sg_publish_data")
check("publish registered in ShotGrid", bool(publish))
fields = ["code", "name", "version_number", "published_file_type", "entity", "task", "path", "sg_status_list", "created_by"]
publish = sg.find_one("PublishedFile", [["id", "is", publish["id"]]], fields)
print("     PublishedFile id %s: %s v%s" % (publish["id"], publish["code"], publish["version_number"]))
check("type is USD Geometry", (publish["published_file_type"] or {}).get("name") == "USD Geometry")
check("linked to the Asset and Task", publish["entity"]["id"] == asset["id"] and publish["task"]["id"] == task["id"])
check("version number is %d" % version, publish["version_number"] == version)
print("     url: %s/detail/PublishedFile/%s" % (sg.base_url, publish["id"]))

# ---- 4. load it back with the data ShotGrid returned
loader = engine.apps["tk-multi-loader2"]
cmds.file(new=True, force=True)
loader.execute_hook_method("actions_hook", "execute_action", name="usd_stage", params=None, sg_publish_data=publish)
proxies = cmds.ls(type="mayaUsdProxyShape")
check("usd_stage loads the real publish", len(proxies) == 1 and os.path.exists(cmds.getAttr(proxies[0] + ".filePath")))
loader.execute_hook_method("actions_hook", "execute_action", name="usd_import", params=None, sg_publish_data=publish)
check("usd_import loads the real publish", len(cmds.ls(type="mesh", noIntermediate=True)) == 1)

print("\nALL CHECKS PASSED")
engine.destroy()
maya.standalone.uninitialize()
