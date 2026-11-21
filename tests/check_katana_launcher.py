"""
Checks what the desktop app would do when launching Katana: which Katana
installs the tk-katana launcher finds, and that the launch environment loads
the Arnold plug-in (KtoA) and our engine. Run with the desktop app's Python:

    "C:\\Program Files\\Shotgun\\Python3\\python.exe" tests\\check_katana_launcher.py

Nothing is launched and it only READS from ShotGrid.
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_CACHE = r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
PROJECT_ID = int(os.environ.get("SG_TEST_PROJECT_ID", "91"))
KATANA_VERSION = "9.0v4"

os.environ["TK_BOOTSTRAP_CONFIG_OVERRIDE"] = os.path.join(REPO, "config")
sys.path.insert(0, os.path.join(BUNDLE_CACHE, "app_store", "tk-core", "v0.24.6", "python"))
import sgtk


def check(label, condition):
    print("%s  %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        raise SystemExit(1)


user = sgtk.authentication.ShotgunAuthenticator().get_default_user()
manager = sgtk.bootstrap.ToolkitManager(user)
manager.plugin_id = "basic.shell"
manager.base_configuration = "sgtk:descriptor:app_store?name=tk-config-basic"
manager.bundle_cache_fallback_paths = [BUNDLE_CACHE]
engine = manager.bootstrap_engine("tk-shell", entity={"type": "Project", "id": PROJECT_ID})

# the bootstrap swapped the Toolkit core: use the module that is live now
sgtk = sys.modules["sgtk"]
launcher = sgtk.platform.create_engine_launcher(
    engine.sgtk, engine.context, "tk-katana", versions=[KATANA_VERSION]
)
check("tk-katana launcher created", launcher is not None)
found = launcher.scan_software()
print("     found:", [(s.version, s.path) for s in found])
check("only Katana %s is offered" % KATANA_VERSION, [s.version for s in found] == [KATANA_VERSION])

info = launcher.prepare_launch(found[0].path, "")
env = info.environment
resources = env["KATANA_RESOURCES"].split(os.pathsep)
print("     KATANA_RESOURCES:")
for entry in resources:
    print("       ", entry)

check("our engine's startup folder comes first",
      resources[0].replace("/", "\\").endswith(r"bundles\tk-katana\katana_resources")
      and os.path.exists(os.path.join(resources[0], "Startup", "init.py")))
ktoa = [r for r in resources if os.path.basename(r).startswith("ktoa-")]
check("a KtoA build for Katana 9.0 is on KATANA_RESOURCES: %s" % [os.path.basename(k) for k in ktoa],
      len(ktoa) == 1 and "-kat9.0-" in ktoa[0] and os.path.isdir(os.path.join(ktoa[0], "Plugins")))
check("Arnold is the default renderer", env.get("DEFAULT_RENDERER") == "arnold")
check("Arnold's bin folder is first on PATH",
      env["PATH"].split(os.pathsep)[0] == os.path.join(ktoa[0], "bin"))
check("every KATANA_RESOURCES entry exists", all(os.path.isdir(r) for r in resources))
check("the launch context is passed on", "SGTK_CONTEXT" in env and env.get("SGTK_ENGINE") == "tk-katana")
check("Toolkit core path is passed on", os.path.isdir(env["SGTK_CORE_PYTHON_PATH"]))

software = engine.shotgun.find_one("Software", [["engine", "is", "tk-katana"]], ["code", "version_names", "projects"])
print("\n     Software entry on the site for tk-katana:", software or "none yet (Katana is not offered in the desktop app)")
print("\nALL CHECKS PASSED")
