"""
Checks F04, the studio folder structure: Toolkit starts with the storage root,
the templates parse, Workfiles is configured, and work and publish paths come
out where the studio layout says.

    "C:\\Program Files\\Shotgun\\Python3\\python.exe" tests\\check_folder_structure.py
    "C:\\Program Files\\Shotgun\\Python3\\python.exe" tests\\check_folder_structure.py --create-folders

Without --create-folders it only reads from ShotGrid. With it, Toolkit creates
the folders of Task 5827 (Model on testAsset) for Maya under the storage root
and records them in ShotGrid (FilesystemLocation entities), which is what
happens the first time an artist opens a task.
"""

import os
import sys

CORE = r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache\app_store\tk-core\v0.24.6\python"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK_ID = 5827
STORAGE = r"C:\Studio_Projects"
PROJECT_FOLDER = os.path.join(STORAGE, "StudioReady_Demo")

failures = []


def check(label, condition, detail=""):
    print("%s  %s%s" % ("PASS" if condition else "FAIL", label, ("  (%s)" % detail) if detail else ""))
    if not condition:
        failures.append(label)


sys.path.insert(0, CORE)
sys.path.insert(0, os.path.join(REPO, "griptape"))
import sg_bridge  # noqa: E402  the sign-in the desktop app saved

sg = sg_bridge.connect()
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
sgtk = sys.modules["sgtk"]  # the bootstrap swaps in the config's core
tk = engine.sgtk
check("Toolkit starts with the primary storage root", True, str(tk.roots))

root = tk.roots.get("primary")
check("primary root is C:\\Studio_Projects/StudioReady_Demo", os.path.normcase(root or "") == os.path.normcase(PROJECT_FOLDER), root)

ours = ["katana_asset_work", "katana_shot_work", "substancepainter_asset_work", "usd_asset_publish",
        "usd_shot_publish", "texture_asset_publish", "render_asset_publish", "render_shot_publish"]
missing = [name for name in ours + ["maya_asset_work", "nuke_asset_work", "maya_shot_work"] if name not in tk.templates]
check("templates parse, ours included (%d templates)" % len(tk.templates), not missing, "missing: %s" % missing)

for env_name in ("asset_step", "shot_step"):
    env = tk.pipeline_configuration.get_environment(env_name)
    for engine_name in ("tk-maya", "tk-nuke"):
        apps = env.get_apps(engine_name)
        has = "tk-multi-workfiles2" in apps
        detail = ""
        if has:
            settings = env.get_app_settings(engine_name, "tk-multi-workfiles2")
            unknown = [settings[k] for k in ("template_work", "template_work_area", "template_publish", "template_publish_area")
                       if settings.get(k) not in tk.templates]
            has = not unknown
            detail = "unknown templates: %s" % unknown if unknown else settings["template_work"]
        check("Workfiles in %s / %s" % (env_name, engine_name), has, detail)

fields = {"sg_asset_type": "Prop", "Asset": "testAsset", "Step": "MDL", "name": "scene", "version": 1}
expected = {
    "maya_asset_work": r"assets\Prop\testAsset\MDL\work\maya\scene.v001.ma",
    "maya_asset_publish": r"assets\Prop\testAsset\MDL\publish\maya\scene.v001.ma",
    "usd_asset_publish": r"assets\Prop\testAsset\MDL\publish\usd\scene.v001.usd",
    "katana_asset_work": r"assets\Prop\testAsset\MDL\work\katana\scene.v001.katana",
}
for name, tail in expected.items():
    path = tk.templates[name].apply_fields(fields)
    check("%s -> ...\\%s" % (name, tail), os.path.normcase(path) == os.path.normcase(os.path.join(PROJECT_FOLDER, tail)), path)
texture = tk.templates["texture_asset_publish"].apply_fields(dict(fields, name="lantern", texture_name="lantern_basecolor", texture_ext="png"))
check("texture publish keeps the <UDIM> token", texture.endswith(r"textures\lantern\v001\lantern_basecolor.<UDIM>.png"), texture)

if "--create-folders" in sys.argv:
    count = tk.create_filesystem_structure("Task", TASK_ID, engine="tk-maya")
    context = tk.context_from_entity("Task", TASK_ID)
    work_area = tk.templates["asset_work_area_maya"].apply_fields(context.as_template_fields(tk.templates["asset_work_area_maya"]))
    check("folders created for Task %d (%d)" % (TASK_ID, count), os.path.isdir(work_area), work_area)
    work = tk.templates["maya_asset_work"]
    path = work.apply_fields(dict(context.as_template_fields(work), name="scene", version=1))
    check("Workfiles would save the first Maya scene as", path.startswith(work_area), path)
else:
    print("SKIP  folder creation (run with --create-folders; writes FilesystemLocation records to ShotGrid)")

engine.destroy()
print("\nALL CHECKS PASSED" if not failures else "\n%d FAILED: %s" % (len(failures), failures))
sys.exit(1 if failures else 0)
