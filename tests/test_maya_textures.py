"""
Headless check of the texture side of the Maya loader (Mari -> Maya and
Painter -> Maya). Run with mayapy:

    "C:\\Program Files\\Autodesk\\Maya2026\\bin\\mayapy.exe" tests\\test_maya_textures.py

It imports the newest USD Geometry publish, then builds materials from
  - the channels the last Mari self-test exported (tests\\run_mari_selftest.ps1), and
  - the newest Painter "Texture" publishes registered in ShotGrid,
and inspects the shading networks. It only READS from ShotGrid.
"""

import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE_CACHE = r"C:\Program Files\Shotgun\Resources\Desktop\Python\bundle_cache"
CORE_PYTHON = os.path.join(BUNDLE_CACHE, "app_store", "tk-core", "v0.24.6", "python")
PROJECT_ID = int(os.environ.get("SG_TEST_PROJECT_ID", "91"))
MARI_RESULT = os.path.join(tempfile.gettempdir(), "sg_pipeline_mari_selftest.json")

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


def source(plug):
    """The node.attr feeding a plug, or None."""
    found = cmds.listConnections(plug, source=True, destination=False, plugs=True)
    return found[0] if found else None


user = sgtk.authentication.ShotgunAuthenticator().get_default_user()
check("saved desktop sign-in found", user is not None)
manager = sgtk.bootstrap.ToolkitManager(user)
manager.plugin_id = "basic.maya"
manager.base_configuration = "sgtk:descriptor:app_store?name=tk-config-basic"
manager.bundle_cache_fallback_paths = [BUNDLE_CACHE]
engine = manager.bootstrap_engine("tk-maya", entity={"type": "Project", "id": PROJECT_ID})
loader = engine.apps["tk-multi-loader2"]
project = {"type": "Project", "id": PROJECT_ID}
fields = ["code", "name", "version_number", "published_file_type", "entity", "task", "path"]


def run(name, publish):
    return loader.execute_hook_method(
        "actions_hook", "execute_action", name=name, params=None, sg_publish_data=publish
    )


def run_many(name, publishes):
    return loader.execute_hook_method(
        "actions_hook", "execute_multiple_actions",
        actions=[{"name": name, "params": None, "sg_publish_data": p} for p in publishes],
    )


# ---- the mesh, from the USD publish
usd = engine.shotgun.find_one(
    "PublishedFile",
    [["project", "is", project], ["published_file_type.PublishedFileType.code", "is", "USD Geometry"],
     ["sg_status_list", "is_not", None]],
    fields, order=[{"field_name": "id", "direction": "desc"}],
)
check("found a USD Geometry publish", usd is not None)
cmds.file(new=True, force=True)
run("usd_import", usd)
meshes = cmds.ls(type="mesh", noIntermediate=True, long=True)
check("mesh imported from %s" % usd["code"], len(meshes) == 1)
mesh = meshes[0]

# ---- actions offered for a Texture publish
mapping = loader.get_setting("action_mappings")["Texture"]

# ---- 1. Mari -> Maya: the channels Mari exported
#         prefer the real publishes Mari registered in ShotGrid; fall back to the
#         files listed by the last Mari self-test
registered = engine.shotgun.find(
    "PublishedFile",
    [["project", "is", project], ["published_file_type.PublishedFileType.code", "is", "Texture"],
     ["sg_status_list", "is_not", None], ["name", "starts_with", "testAsset_model_"]],
    fields, order=[{"field_name": "version_number", "direction": "desc"}],
)
newest = {}
for publish in registered:
    newest.setdefault(publish["name"], publish)
mari_textures = list(newest.values())
if mari_textures:
    print("     using %d Mari publishes registered in ShotGrid: ids %s"
          % (len(mari_textures), sorted(p["id"] for p in mari_textures)))
else:
    check("Mari self-test result available (%s)" % MARI_RESULT, os.path.exists(MARI_RESULT))
    with open(MARI_RESULT) as handle:
        mari_textures = json.load(handle).get("texture_publishes", [])
    print("     using the files listed by the last Mari self-test")
check("Mari textures to load (%d)" % len(mari_textures), len(mari_textures) > 0)
print("     ", [t["name"] for t in mari_textures])

offered = loader.execute_hook_method(
    "actions_hook", "generate_actions", sg_publish_data=mari_textures[0], actions=mapping, ui_area="main"
)
check("loader offers %s" % [a["name"] for a in offered],
      {"sgp_build_material", "sgp_texture_node", "texture_node", "image_plane"} == {a["name"] for a in offered})

cmds.select(mesh, replace=True)
run_many("sgp_build_material", mari_textures)

prefix = mari_textures[0]["name"].rsplit("_", 1)[0]
material = "%s_mtl" % prefix
shading_group = "%s_SG" % prefix
built = [m for m in cmds.ls(type="standardSurface") if m.endswith("_mtl")]
check("one material built for the Mari textures: %s" % built, built == [material])
check("material assigned to the mesh",
      shading_group in (cmds.listConnections(mesh, type="shadingEngine") or []))

maps = {t["name"].rsplit("_", 1)[-1] for t in mari_textures}
if "basecolor" in maps:
    plug = source(material + ".baseColor")
    check("basecolor -> baseColor (%s)" % plug, plug is not None and plug.endswith(".outColor"))
    base_file = plug.split(".")[0]
    path = cmds.getAttr(base_file + ".fileTextureName")
    check("file node points at an existing tile: %s" % os.path.basename(path), os.path.exists(path))
    check("file node uses UDIM tiling", cmds.getAttr(base_file + ".uvTilingMode") == 3)
    check("basecolor keeps a colour-managed colour space (%s)" % cmds.getAttr(base_file + ".colorSpace"),
          cmds.getAttr(base_file + ".colorSpace").lower() != "raw")
    r, g, b = cmds.colorAtPoint(base_file, u=0.5, v=0.5, output="RGB")
    check("basecolor samples as the red fill (%.2f %.2f %.2f)" % (r, g, b), r > 0.3 and r > 3 * g and r > 3 * b)
if "roughness" in maps:
    plug = source(material + ".specularRoughness")
    check("roughness -> specularRoughness (%s)" % plug, plug is not None and plug.endswith(".outAlpha"))
    rough_file = plug.split(".")[0]
    check("roughness is read Raw with alpha from luminance",
          cmds.getAttr(rough_file + ".colorSpace").lower().endswith("raw")
          and cmds.getAttr(rough_file + ".alphaIsLuminance"))
if "metallic" in maps:
    plug = source(material + ".metalness")
    check("metallic -> metalness (%s)" % plug, plug is not None and plug.endswith(".outAlpha"))
if "normal" in maps:
    plug = source(material + ".normalCamera")
    check("normal -> bump2d -> normalCamera (%s)" % plug, plug is not None and cmds.nodeType(plug.split(".")[0]) == "bump2d")
    check("bump2d is set to tangent space normals", cmds.getAttr(plug.split(".")[0] + ".bumpInterp") == 1)
if "height" in maps:
    plug = source(shading_group + ".displacementShader")
    check("height -> displacementShader on the shading group (%s)" % plug,
          plug is not None and cmds.nodeType(plug.split(".")[0]) == "displacementShader")

# ---- 2. Painter -> Maya: the real Texture publishes on the site
site_textures = engine.shotgun.find(
    "PublishedFile",
    [["project", "is", project], ["published_file_type.PublishedFileType.code", "is", "Texture"],
     ["sg_status_list", "is_not", None]],
    fields, order=[{"field_name": "version_number", "direction": "desc"}],
)
latest = {}
for publish in site_textures:
    latest.setdefault(publish["name"], publish)
painter_textures = [p for p in latest.values() if p["name"].startswith("testMtlSG_")]
check("found Painter Texture publishes on the site (%d)" % len(painter_textures), len(painter_textures) > 0)

cmds.select(clear=True)
run_many("sgp_build_material", painter_textures)
check("material built from the site's publishes, nothing selected so nothing reassigned",
      cmds.objExists("testMtlSG_mtl")
      and shading_group in (cmds.listConnections(mesh, type="shadingEngine") or []))
check("it has as many file nodes as publishes",
      len([f for f in cmds.ls(type="file") if f.startswith("testMtlSG_")]) == len(painter_textures))

# ---- 3. single file node
before = set(cmds.ls(type="file"))
run("sgp_texture_node", painter_textures[0])
new_files = set(cmds.ls(type="file")) - before
check("Create Texture Node (UDIM) makes one file node", len(new_files) == 1)

# ---- 4. Griptape -> Maya: textures published by the Griptape node, if any
griptape_textures = [p for p in latest.values() if p["name"].startswith("griptapeTest_")]
if griptape_textures:
    print("     Griptape publishes: ids %s" % sorted(p["id"] for p in griptape_textures))
    cmds.select(clear=True)
    run_many("sgp_build_material", griptape_textures)
    check("material built from the Griptape texture", cmds.objExists("griptapeTest_mtl"))
    plug = source("griptapeTest_mtl.baseColor")
    check("its base colour is fed by a file node (%s)" % plug, plug is not None)
    griptape_file = plug.split(".")[0]
    path = cmds.getAttr(griptape_file + ".fileTextureName")
    check("the file node points at Griptape's tile: %s" % os.path.basename(path), os.path.exists(path))
    check("it uses UDIM tiling", cmds.getAttr(griptape_file + ".uvTilingMode") == 3)
    r, g, b = cmds.colorAtPoint(griptape_file, u=0.5, v=0.5, output="RGB")
    check("it samples as the red image Griptape published (%.2f %.2f %.2f)" % (r, g, b), r > 0.3 and r > 3 * g)
else:
    print("SKIP  no Griptape texture on the site: run tests\\test_griptape_nodes.py --publish")
print("\nALL CHECKS PASSED")
engine.destroy()
maya.standalone.uninitialize()
