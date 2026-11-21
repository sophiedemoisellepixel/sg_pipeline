"""
Check of the Maya -> Painter link that runs WITHOUT Painter, using the Python
that ships with it (same Python and PySide6 as the application):

    "C:\\Program Files\\Adobe\\Adobe Substance 3D Painter\\resources\\pythonsdk\\python.exe" tests\\test_painter_engine.py

Painter's `substance_painter` module is replaced by a small recording stub, so
this proves the Toolkit side (startup plugin, engine, menu, loader app, loader
actions, launcher) but NOT that Painter itself accepts the calls. It only reads
from ShotGrid and needs at least one "USD Geometry" publish in the project.
"""

import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_CACHE = r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
CORE_PYTHON = os.path.join(BUNDLE_CACHE, "app_store", "tk-core", "v0.24.6", "python")
ENGINE_DIR = os.path.join(REPO, "config", "bundles", "tk-substancepainter")
PROJECT_ID = int(os.environ.get("SG_TEST_PROJECT_ID", "91"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["TK_BOOTSTRAP_CONFIG_OVERRIDE"] = os.path.join(REPO, "config")
os.environ["SGTK_CORE_PYTHON_PATH"] = CORE_PYTHON
os.environ["SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS"] = BUNDLE_CACHE
os.environ["SHOTGUN_ENTITY_TYPE"] = "Project"
os.environ["SHOTGUN_ENTITY_ID"] = str(PROJECT_ID)
os.environ.pop("SGTK_CONTEXT", None)

# Painter's PySide6 needs the Qt libraries that sit next to the Painter executable
PAINTER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
if hasattr(os, "add_dll_directory") and os.path.isdir(PAINTER_DIR):
    os.add_dll_directory(PAINTER_DIR)
    os.environ["PATH"] = PAINTER_DIR + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("QT_PLUGIN_PATH", os.path.join(PAINTER_DIR, "PlugIns"))

from PySide6 import QtWidgets

qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
main_window = QtWidgets.QMainWindow()


def check(label, condition):
    print("%s  %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        raise SystemExit(1)


# ---- a recording stand-in for Painter's Python API -------------------------
import dataclasses
import enum

calls = []
state = {"open": False, "dirty": False, "metadata": {}, "menus": []}

sp = types.ModuleType("substance_painter")
sp.__path__ = []

sp_logging = types.ModuleType("substance_painter.logging")
sp_logging.DBG_INFO = "DBG_INFO"
sp_logging.messages = []
for _level in ("info", "warning", "error"):
    setattr(sp_logging, _level, lambda m, _l=_level: sp_logging.messages.append((_l, m)))
sp_logging.log = lambda severity, channel, m: sp_logging.messages.append(("debug", m))

sp_application = types.ModuleType("substance_painter.application")
sp_application.version = lambda: "12.1.5"

sp_ui = types.ModuleType("substance_painter.ui")
sp_ui.get_main_window = lambda: main_window
sp_ui.add_menu = lambda menu: state["menus"].append(menu)
sp_ui.delete_ui_element = lambda element: state["menus"].remove(element)

sp_project = types.ModuleType("substance_painter.project")


class ProjectWorkflow(enum.Enum):
    Default = 0
    TextureSetPerUVTile = 1
    UVTile = 2


class ReloadMeshStatus(enum.Enum):
    SUCCESS = 0
    ERROR = 2


@dataclasses.dataclass
class UsdSettings:
    scope_name: str = "/"
    variants: dict = None
    subdivision_level: int = 1
    frame: int = 0


@dataclasses.dataclass
class Settings:
    import_cameras: bool = None
    project_workflow: ProjectWorkflow = None
    mesh_settings: UsdSettings = None


@dataclasses.dataclass
class MeshReloadingSettings:
    import_cameras: bool = True
    preserve_strokes: bool = True
    mesh_settings: UsdSettings = None


class Metadata:
    def __init__(self, context):
        self._data = state["metadata"].setdefault(context, {})

    def set(self, key, value):
        self._data[key] = value

    def get(self, key):
        return self._data[key]


def _create(mesh_file_path, mesh_map_file_paths=None, template_file_path=None, settings=None):
    if state["open"]:
        raise RuntimeError("Cannot create a new project because one is already opened.")
    calls.append(("create", mesh_file_path, settings))
    state["open"] = True


def _reload_mesh(mesh_file_path, settings, loading_status_cb):
    calls.append(("reload_mesh", mesh_file_path, settings))
    loading_status_cb(ReloadMeshStatus.SUCCESS)


def _close():
    calls.append(("close",))
    state["open"] = False


sp_project.ProjectWorkflow = ProjectWorkflow
sp_project.ReloadMeshStatus = ReloadMeshStatus
sp_project.UsdSettings = UsdSettings
sp_project.Settings = Settings
sp_project.MeshReloadingSettings = MeshReloadingSettings
sp_project.Metadata = Metadata
sp_project.create = _create
sp_project.reload_mesh = _reload_mesh
sp_project.close = _close
sp_project.is_open = lambda: state["open"]
sp_project.needs_saving = lambda: state["dirty"]
sp_project.execute_when_not_busy = lambda callback: callback()

for _name, _module in (("logging", sp_logging), ("application", sp_application), ("ui", sp_ui), ("project", sp_project)):
    setattr(sp, _name, _module)
    sys.modules["substance_painter." + _name] = _module
sys.modules["substance_painter"] = sp

# ---- 1. the startup plugin starts the engine -------------------------------
sys.path.insert(0, os.path.join(ENGINE_DIR, "painter", "startup"))
import tk_substancepainter_startup as startup_plugin

startup_plugin.start_plugin()
errors = [m for level, m in sp_logging.messages if level == "error"]
if errors:
    print(errors[-1])
check("startup plugin reported no errors", not errors)

import sgtk

engine = sgtk.platform.current_engine()
check("tk-substancepainter engine is running", engine is not None and engine.name == "tk-substancepainter")
check("engine context is the project (%s)" % engine.context, engine.context.project["id"] == PROJECT_ID)
check("loader app loaded", "tk-multi-loader2" in engine.apps)

# ---- 2. menu ----------------------------------------------------------------
check("one menu added to Painter", len(state["menus"]) == 1)
menu = state["menus"][0]
labels = [a.text() for a in menu.actions() if not a.isSeparator()]
print("     menu:", labels)
check("menu shows the context and the Loader", labels[0] == str(engine.context) and any("Load" in l for l in labels))

# ---- 3. loader actions on a real USD Geometry publish -----------------------
fields = ["code", "name", "version_number", "published_file_type", "entity", "task", "path"]
publish = engine.shotgun.find_one(
    "PublishedFile",
    [["project", "is", {"type": "Project", "id": PROJECT_ID}],
     ["published_file_type.PublishedFileType.code", "is", "USD Geometry"],
     ["sg_status_list", "is_not", None]],
    fields,
    order=[{"field_name": "id", "direction": "desc"}],
)
check("found a USD Geometry publish to load", publish is not None)
print("     publish:", publish["id"], publish["code"])

loader = engine.apps["tk-multi-loader2"]
mapped = loader.get_setting("action_mappings")["USD Geometry"]
actions = loader.execute_hook_method(
    "actions_hook", "generate_actions", sg_publish_data=publish, actions=mapped, ui_area="main"
)
check("loader offers both Painter actions", [a["name"] for a in actions] == ["painter_new_project", "painter_update_mesh"])

loader.execute_hook_method("actions_hook", "execute_action", name="painter_new_project", params=None, sg_publish_data=publish)
name, mesh_path, settings = calls[-1]
check("new project created from the published USD", name == "create" and os.path.exists(mesh_path) and mesh_path.endswith(".usd"))
check("UDIM workflow, no cameras, no extra subdivision",
      settings.project_workflow is ProjectWorkflow.UVTile and settings.import_cameras is False
      and settings.mesh_settings.subdivision_level == 0)
record = state["metadata"]["sg_pipeline"]["source_publish"]
check("source publish stored in the project metadata", record["id"] == publish["id"] and record["entity_id"] == publish["entity"]["id"])

loader.execute_hook_method("actions_hook", "execute_action", name="painter_update_mesh", params=None, sg_publish_data=publish)
check("update mesh keeps strokes", calls[-1][0] == "reload_mesh" and calls[-1][2].preserve_strokes is True)

state["dirty"] = True
try:
    loader.execute_hook_method("actions_hook", "execute_action", name="painter_new_project", params=None, sg_publish_data=publish)
    refused = False
except Exception as e:
    refused = "unsaved changes" in str(e)
check("new project refuses to discard unsaved work", refused and calls[-1][0] == "reload_mesh")
state["dirty"] = False

# ---- 4. launcher (what the desktop app would run) ----------------------------
launcher = sgtk.platform.create_engine_launcher(engine.sgtk, engine.context, "tk-substancepainter")
found = launcher.scan_software()
print("     software:", [(s.product, s.version, s.path) for s in found])
check("launcher finds the installed Painter with its version", len(found) == 1 and found[0].version.split(".")[0].isdigit() and found[0].version != "0.0.0")
info = launcher.prepare_launch(found[0].path, "")
env = info.environment
check("launch environment points Painter at the plugin and the core",
      os.path.isdir(os.path.join(env["SUBSTANCE_PAINTER_PLUGINS_PATH"].split(os.pathsep)[0], "startup"))
      and os.path.isdir(os.path.join(env["SGTK_CORE_PYTHON_PATH"], "tank"))
      and env["SGTK_ENGINE"] == "tk-substancepainter" and "SGTK_CONTEXT" in env)
check("launch environment passes on the desktop app's bundle cache",
      BUNDLE_CACHE in env.get("SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS", "").split(os.pathsep))

# ---- 5. shutdown -------------------------------------------------------------
startup_plugin.close_plugin()
check("menu removed on shutdown", state["menus"] == [] and sgtk.platform.current_engine() is None)

print("\nALL CHECKS PASSED")
