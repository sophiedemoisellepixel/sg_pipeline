"""
Checks that the desktop app's launcher (tk-multi-launchapp) would offer
Substance 3D Painter, Mari and Katana for the test project, by running the same app in
a shell engine. Run with the desktop app's Python:

    "C:\\Program Files\\Shotgun\\Python3\\python.exe" tests\\check_desktop_launcher.py [--create]

With --create it first adds the Software entries for our in-house engines to
the site if they are missing (WRITES to ShotGrid, restricted to the test project).
Without it, it only reads.
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_CACHE = r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
PROJECT_ID = int(os.environ.get("SG_TEST_PROJECT_ID", "91"))
# engine -> (Software entry name, word expected in the launch command name)
SOFTWARE = {
    "tk-substancepainter": ("Substance 3D Painter", "painter"),
    "tk-mari": ("Mari", "mari"),
    "tk-katana": ("Katana", "katana"),
}
# engine -> the only versions to offer (Software.version_names); others are hidden
VERSIONS = {"tk-katana": "9.0v4"}

os.environ["TK_BOOTSTRAP_CONFIG_OVERRIDE"] = os.path.join(REPO, "config")
sys.path.insert(0, os.path.join(BUNDLE_CACHE, "app_store", "tk-core", "v0.24.6", "python"))
import sgtk


def check(label, condition):
    print("%s  %s" % ("PASS" if condition else "FAIL", label))
    if not condition:
        raise SystemExit(1)


user = sgtk.authentication.ShotgunAuthenticator().get_default_user()
sg = user.create_sg_connection()
project = {"type": "Project", "id": PROJECT_ID}

for engine_name, (code, command_word) in SOFTWARE.items():
    software = sg.find_one("Software", [["engine", "is", engine_name]], ["code", "projects"])
    if software is None and "--create" in sys.argv:
        software = sg.create(
            "Software",
            {
                "code": code,
                "engine": engine_name,
                # only offered in the test project; clear this field to offer it everywhere
                "projects": [project],
                "description": "Launches %s with the sg_pipeline Toolkit engine." % code,
                **({"version_names": VERSIONS[engine_name]} if engine_name in VERSIONS else {}),
            },
            return_fields=["code", "projects"],
        )
        print("     created Software id %s (%s)" % (software["id"], code))
    check(
        "Software entry for %s exists (id %s, projects %s)"
        % (engine_name, software and software["id"], software and [p["name"] for p in software["projects"]]),
        software is not None,
    )

manager = sgtk.bootstrap.ToolkitManager(user)
manager.plugin_id = "basic.shell"
manager.base_configuration = "sgtk:descriptor:app_store?name=tk-config-basic"
manager.bundle_cache_fallback_paths = [BUNDLE_CACHE]
engine = manager.bootstrap_engine("tk-shell", entity=project)

launchers = sorted(
    name for name, cmd in engine.commands.items()
    if cmd["properties"].get("app") is engine.apps.get("tk-multi-launchapp")
)
print("     launch commands:", launchers)
for engine_name, (code, command_word) in SOFTWARE.items():
    check("launcher offers %s" % code, any(command_word in name.lower() for name in launchers))
print("\nALL CHECKS PASSED")
