"""
Headless check of the USD side of the Nuke loader (Maya -> Nuke). Run with
Nuke in terminal mode, using the interactive licence:

    "C:\\Program Files\\Nuke17.1v3\\Nuke17.1.exe" -t -i tests\\test_nuke_usd.py

It loads the newest USD Geometry publish with both loader actions and checks
that Nuke reads geometry from it. It only READS from ShotGrid.
"""

import os
import sys

import nuke

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_CACHE = r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
CORE_PYTHON = os.path.join(BUNDLE_CACHE, "app_store", "tk-core", "v0.24.6", "python")
PROJECT_ID = int(os.environ.get("SG_TEST_PROJECT_ID", "91"))

os.environ["TK_BOOTSTRAP_CONFIG_OVERRIDE"] = os.path.join(REPO, "config")
sys.path.insert(0, CORE_PYTHON)
import sgtk


def check(label, condition):
    print("%s  %s" % ("PASS" if condition else "FAIL", label))
    sys.stdout.flush()
    if not condition:
        raise SystemExit(1)


user = sgtk.authentication.ShotgunAuthenticator().get_default_user()
check("saved desktop sign-in found", user is not None)
manager = sgtk.bootstrap.ToolkitManager(user)
manager.plugin_id = "basic.nuke"
manager.base_configuration = "sgtk:descriptor:app_store?name=tk-config-basic"
manager.bundle_cache_fallback_paths = [BUNDLE_CACHE]
project = {"type": "Project", "id": PROJECT_ID}
engine = manager.bootstrap_engine("tk-nuke", entity=project)
check("tk-nuke engine started in Nuke %s" % nuke.NUKE_VERSION_STRING, engine is not None)
loader = engine.apps["tk-multi-loader2"]

usd = engine.shotgun.find_one(
    "PublishedFile",
    [["project", "is", project], ["published_file_type.PublishedFileType.code", "is", "USD Geometry"],
     ["sg_status_list", "is_not", None]],
    ["code", "name", "version_number", "published_file_type", "entity", "task", "path"],
    order=[{"field_name": "id", "direction": "desc"}],
)
check("found a USD Geometry publish", usd is not None)
print("     ", usd["id"], usd["code"])

mapping = loader.get_setting("action_mappings")["USD Geometry"]
offered = loader.execute_hook_method(
    "actions_hook", "generate_actions", sg_publish_data=usd, actions=mapping, ui_area="main"
)
check("loader offers %s" % [a["name"] for a in offered],
      [a["name"] for a in offered] == ["nuke_geo_import", "nuke_read_geo"])


def run(name):
    return loader.execute_hook_method(
        "actions_hook", "execute_action", name=name, params=None, sg_publish_data=usd
    )


# ---- USD-based 3D system
geo_import = run("nuke_geo_import")
check("GeoImport node created: %s" % geo_import.name(), geo_import.Class() == "GeoImport")
check("it points at the published file", os.path.exists(geo_import["file"].value()))
check("it carries the version as its label (%s)" % geo_import["label"].value(),
      geo_import["label"].value() == "v%03d" % usd["version_number"])
check("GeoImport reports no error", not geo_import.hasError())

# ---- classic 3D system
read_geo = run("nuke_read_geo")
check("ReadGeo node created: %s (%s)" % (read_geo.name(), read_geo.Class()),
      read_geo.Class().startswith("ReadGeo"))
check("ReadGeo reports no error", not read_geo.hasError())

# ---- the stock actions still work through the chained hook
texture = engine.shotgun.find_one(
    "PublishedFile",
    [["project", "is", project], ["published_file_type.PublishedFileType.code", "is", "Texture"],
     ["sg_status_list", "is_not", None]],
    ["code", "name", "version_number", "published_file_type", "entity", "task", "path"],
    order=[{"field_name": "id", "direction": "desc"}],
)
if texture:
    before = len(nuke.allNodes("Read"))
    loader.execute_hook_method(
        "actions_hook", "execute_action", name="read_node", params=None, sg_publish_data=texture
    )
    check("stock read_node still makes a Read node for a Texture publish (%s)" % texture["code"],
          len(nuke.allNodes("Read")) == before + 1)

# ---- Katana -> Nuke: the frames Katana rendered, as a Read node
#      prefer a real publish registered in ShotGrid; fall back to what the last
#      Katana self-test (tests\run_katana_selftest.ps1) would have published
import json
import tempfile
from urllib.parse import quote

render = engine.shotgun.find_one(
    "PublishedFile",
    [["project", "is", project], ["published_file_type.PublishedFileType.code", "is", "Rendered Image"],
     ["sg_status_list", "is_not", None], ["name", "starts_with", "katana_test_"]],
    ["code", "name", "version_number", "published_file_type", "entity", "task", "path"],
    order=[{"field_name": "id", "direction": "desc"}],
)
if render:
    print("     using the Katana render registered in ShotGrid: id %s" % render["id"])
else:
    katana_result = os.path.join(tempfile.gettempdir(), "sg_pipeline_katana_selftest.json")
    renders = []
    if os.path.exists(katana_result):
        with open(katana_result) as handle:
            renders = json.load(handle).get("render_publishes", [])
    render = renders[0] if renders else None
    if render:
        print("     using the render listed by the last Katana self-test")
if render:
    before = set(nuke.allNodes("Read"))
    loader.execute_hook_method(
        "actions_hook", "execute_action", name="read_node", params=None, sg_publish_data=render
    )
    new_reads = [n for n in nuke.allNodes("Read") if n not in before]
    check("Rendered Image publish makes a Read node (%s)" % render["code"], len(new_reads) == 1)
    read = new_reads[0]
    print("     ", read["file"].value(), read["first"].value(), "-", read["last"].value())
    check("Read node points at the frame sequence", "%04d" in read["file"].value())
    check("Read node has the rendered frame range 1-2",
          int(read["first"].value()) == 1 and int(read["last"].value()) == 2)
    check("Read node reports no error", not read.hasError())
    check("the image has the render resolution (%sx%s)" % (read.width(), read.height()),
          read.width() == 512 and read.height() == 512)
else:
    print("SKIP  no Katana render to load: run tests\\run_katana_selftest.ps1 first")

# ---- Nuke -> Griptape: write the comp as PNG and run the publisher on it
#      (Griptape reads PNG, JPEG and TIFF, not EXR). With SG_PIPELINE_SELFTEST_PUBLISH=1
#      the frames are registered in ShotGrid (WRITES); otherwise nothing is.
if render:
    work = os.path.join(os.path.dirname(REPO), "sg_pipeline_work", "nuke_test")
    os.makedirs(os.path.join(work, "renders"), exist_ok=True)
    write = nuke.nodes.Write(inputs=[read], name="GriptapeOut")
    write["file"].fromUserText(os.path.join(work, "renders", "katana_test_comp.%04d.png").replace("\\", "/"))
    write["file_type"].setValue("png")
    nuke.execute(write, 1, 2)
    frames = [os.path.join(work, "renders", "katana_test_comp.%04d.png" % f) for f in (1, 2)]
    check("Nuke wrote the comp as PNG frames", all(os.path.exists(f) for f in frames))
    script = os.path.join(work, "katana_test_comp_v001.nk").replace("\\", "/")
    nuke.scriptSaveAs(script, overwrite=1)

    publisher = engine.apps["tk-multi-publish2"]
    manager = publisher.create_publish_manager()
    manager.collect_session()
    collected = [(item.type_spec, item.name) for item in manager.tree]
    print("     collected:", collected)
    image_items = [item for item in manager.tree if item.type_spec == "file.image.sequence"]
    check("the publisher collects the Write node's frames", len(image_items) == 1)
    comp_item = image_items[0]
    print("     plugins on it:", [t.name for t in comp_item.tasks])
    check("the frames get the stock publish plugin",
          "Publish to Flow Production Tracking" in [t.name for t in comp_item.tasks])
    if os.environ.get("SG_PIPELINE_SELFTEST_PUBLISH") == "1":
        for item in manager.tree:
            item.description = "sg_pipeline Nuke self-test"
        # only the frames: leave the script and review items unpublished
        for item in manager.tree:
            for task in item.tasks:
                task.active = item is comp_item and task.name == "Publish to Flow Production Tracking"
        failed = manager.validate()
        check("publish validation passes %s" % [str(f) for f in failed], not failed)
        manager.publish()
        manager.finalize()
        data = comp_item.properties.get("sg_publish_data") or {}
        print("     registered publish id %s (%s)" % (data.get("id"), data.get("code")))
        check("the comp frames are registered in ShotGrid", bool(data.get("id")))

print("\nALL CHECKS PASSED")
sys.stdout.flush()
engine.destroy()
