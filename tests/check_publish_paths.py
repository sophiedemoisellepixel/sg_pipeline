"""
Checks where the publishers put files (config/hooks/lib/sg_pipeline_templates.py):
the studio templates for a task, the old zero-config paths otherwise.

    "C:\\Program Files\\Shotgun\\Python3\\python.exe" tests\\check_publish_paths.py

Starts Toolkit with the config for Task 5827 (Model on testAsset, a Prop) and
only reads from ShotGrid; the task's folders already exist.
"""

import importlib.util
import os
import sys

CORE = r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache\app_store\tk-core\v0.24.6\python"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK_ID = 5827
STEP = r"C:\Studio_Projects\StudioReady_Demo\assets\Prop\testAsset\MDL"

failures = []


def check(label, condition, detail=""):
    print("%s  %s%s" % ("PASS" if condition else "FAIL", label, ("  (%s)" % (detail,)) if detail else ""))
    if not condition:
        failures.append(label)


sys.path.insert(0, CORE)
sys.path.insert(0, os.path.join(REPO, "griptape"))
import sg_bridge  # noqa: E402

sg_bridge.connect()
import sgtk  # noqa: E402
from tank.authentication import session_cache  # noqa: E402

os.environ["TK_BOOTSTRAP_CONFIG_OVERRIDE"] = os.path.join(REPO, "config")
login = session_cache.get_current_user(sg_bridge.SITE)
session = session_cache.get_session_data(sg_bridge.SITE, login)
user = sgtk.authentication.ShotgunAuthenticator().create_session_user(
    login=session["login"], session_token=session["session_token"], host=sg_bridge.SITE,
    session_metadata=session.get("session_metadata"),
)
manager = sgtk.bootstrap.ToolkitManager(user)
manager.plugin_id = "basic.shell"
engine = manager.bootstrap_engine("tk-shell", entity={"type": "Task", "id": TASK_ID})
tk = engine.sgtk
task = engine.context
project = tk.context_from_entity("Project", task.project["id"])

spec = importlib.util.spec_from_file_location("sg_pipeline_templates", os.path.join(REPO, "config", "hooks", "lib", "sg_pipeline_templates.py"))
paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paths)


def same(a, b):
    return a is not None and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


# ---- Maya USD
scene = os.path.join(STEP, "work", "maya", "scene.v003.ma")
result = paths.maya_usd_publish(tk, task, scene)
check("Maya: a work-area scene publishes to publish/usd with its name and version",
      result is not None and same(result[0], os.path.join(STEP, "publish", "usd", "scene.v003.usd")) and result[1] == 3,
      result)
check("Maya: a scene outside the work area keeps the old path (None)",
      paths.maya_usd_publish(tk, task, r"C:\temp\prop_model_v001.ma") is None)
check("Maya: no task (project context) keeps the old path (None)",
      paths.maya_usd_publish(tk, project, scene) is None)

# ---- Painter
spp = os.path.join(STEP, "work", "substancepainter", "texturing.v002.spp")
result = paths.painter_texture_folder(tk, task, spp)
check("Painter: textures of a work-area project go to publish/textures/<name>/v###",
      result is not None and same(result[0], os.path.join(STEP, "publish", "textures", "texturing", "v002")) and result[1] == 2,
      result)
check("Painter: a project saved elsewhere keeps the old path (None)",
      paths.painter_texture_folder(tk, task, r"C:\temp\texturing_v002.spp") is None)

# ---- Mari
mari = paths.mari_texture_path(tk, task, "testAsset_testAsset_model_v003", "testAsset_model_basecolor", 4, "png")
check("Mari: a channel goes to publish/textures/<mari project>/v###/<name>.<UDIM>.png",
      same(mari, os.path.join(STEP, "publish", "textures", "testAssettestAssetmodelv003", "v004", "testAsset_model_basecolor.<UDIM>.png")),
      mari)
check("Mari: 16-bit channels keep exr",
      (paths.mari_texture_path(tk, task, "p", "x_height", 1, "exr") or "").endswith(".<UDIM>.exr"))
check("Mari: no task keeps the old export root (None)",
      paths.mari_texture_path(tk, project, "p", "x_basecolor", 1, "png") is None)

check("template names keep letters and digits only", paths.template_name_key("testAsset_model v3") == "testAssetmodelv3")

engine.destroy()
print("\nALL CHECKS PASSED" if not failures else "\n%d FAILED: %s" % (len(failures), failures))
sys.exit(1 if failures else 0)
