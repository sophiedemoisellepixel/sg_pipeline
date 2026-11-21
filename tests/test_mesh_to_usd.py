"""
Checks griptape/mesh_to_usd.py and the ShotGridPublish3D Griptape node, with
the Python of Griptape's engine:

    "%LOCALAPPDATA%\\ai.griptape.nodes.desktop\\current\\resources\\engine-bundle\\python\\python.exe" tests\\test_mesh_to_usd.py

1. Writes a small GLB by hand (two placements of one textured cube, with an
   interleaved buffer, embedded PNG textures and node transforms), converts
   it, and checks the USD with Katana's USD library and with Maya's USD import.
2. Packs that USD as USDZ and converts the package back.
3. Has Maya write an FBX cube and converts it (through mayapy).
4. Runs the ShotGridPublish3D node on the GLB as a dry run (reads ShotGrid,
   registers nothing). Needs a valid desktop-app sign-in; skipped otherwise.

Everything is written under sg_pipeline_work/mesh_to_usd_test.
"""

import importlib.util
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(os.path.dirname(REPO), "sg_pipeline_work", "mesh_to_usd_test")
KATANA = r"C:\Program Files\Katana9.0v4"
MAYAPY = r"C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe"
sys.path.insert(0, os.path.join(REPO, "griptape"))
import mesh_to_usd  # noqa: E402


def check(label, condition):
    print("%s  %s" % ("PASS" if condition else "FAIL", label))
    sys.stdout.flush()
    if not condition:
        raise SystemExit(1)


def png(color, size=8):
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


def write_test_glb(path):
    """A unit cube placed twice, textured, with an interleaved position/normal buffer."""
    faces = [  # normal, then 4 corners counter-clockwise seen from outside
        ((1, 0, 0), [(1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1)]),
        ((-1, 0, 0), [(-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)]),
        ((0, 1, 0), [(-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1)]),
        ((0, -1, 0), [(-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)]),
        ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
        ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
    ]
    interleaved, uvs, indices = [], [], []
    for face, (normal, corners) in enumerate(faces):
        for corner in corners:
            interleaved.append([c * 0.5 for c in corner] + list(normal))
        uvs += [(0, 1), (1, 1), (1, 0), (0, 0)]
        base = face * 4
        indices += [base, base + 1, base + 2, base, base + 2, base + 3]

    blobs = [
        np.array(interleaved, dtype="<f4").tobytes(),
        np.array(uvs, dtype="<f4").tobytes(),
        np.array(indices, dtype="<u2").tobytes(),
        png((204, 26, 26)),
        png((0, 128, 0)),  # roughness 0.5 (green), metallic 0 (blue)
    ]
    binary, views = b"", []
    for blob in blobs:
        binary += b"\0" * (-len(binary) % 4)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(blob)})
        binary += blob
    binary += b"\0" * (-len(binary) % 4)
    views[0]["byteStride"] = 24

    half = math.sqrt(0.5)
    document = {
        "asset": {"version": "2.0", "generator": "sg_pipeline test"},
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": [
            {"name": "small", "mesh": 0, "translation": [1, 0, 0], "scale": [0.5, 0.5, 0.5]},
            {"name": "turned", "mesh": 0, "translation": [-1, 0, 0], "rotation": [0, half, 0, half]},
        ],
        "meshes": [{"name": "cube", "primitives": [{
            "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3, "material": 0}]}],
        "materials": [{"name": "painted", "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0}, "metallicRoughnessTexture": {"index": 1}}}],
        "textures": [{"source": 0}, {"source": 1}],
        "images": [{"name": "basecolor", "bufferView": 3, "mimeType": "image/png"},
                   {"name": "metal_rough", "bufferView": 4, "mimeType": "image/png"}],
        "accessors": [
            {"bufferView": 0, "byteOffset": 0, "componentType": 5126, "count": 24, "type": "VEC3",
             "min": [-0.5, -0.5, -0.5], "max": [0.5, 0.5, 0.5]},
            {"bufferView": 0, "byteOffset": 12, "componentType": 5126, "count": 24, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 24, "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(binary)}],
    }
    text = json.dumps(document).encode("utf-8")
    text += b" " * (-len(text) % 4)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(text) + 8 + len(binary)))
        handle.write(struct.pack("<II", len(text), 0x4E4F534A) + text)
        handle.write(struct.pack("<II", len(binary), 0x004E4942) + binary)
    return document


KATANA_CHECK = r'''
import json, os, sys
from fnpxr import Usd, UsdGeom, UsdShade, Sdf, UsdUtils
path, usdz = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""
stage = Usd.Stage.Open(path)
result = {"opened": stage is not None}
meshes = [UsdGeom.Mesh(p) for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)]
result["default_prim"] = stage.GetDefaultPrim().GetName() if stage.GetDefaultPrim() else None
result["meters_per_unit"] = UsdGeom.GetStageMetersPerUnit(stage)
result["up_axis"] = UsdGeom.GetStageUpAxis(stage)
result["meshes"] = len(meshes)
result["points"] = [len(m.GetPointsAttr().Get()) for m in meshes]
result["has_st"] = [UsdGeom.PrimvarsAPI(m).HasPrimvar("st") for m in meshes]
cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
box = cache.ComputeWorldBound(stage.GetPseudoRoot()).ComputeAlignedRange()
result["bbox_min"] = list(box.GetMin()); result["bbox_max"] = list(box.GetMax())
textures = []
bound = []
for mesh in meshes:
    material, _ = UsdShade.MaterialBindingAPI(mesh.GetPrim()).ComputeBoundMaterial()
    bound.append(bool(material))
for prim in stage.Traverse():
    shader = UsdShade.Shader(prim)
    if shader and shader.GetIdAttr().Get() == "UsdUVTexture":
        asset = shader.GetInput("file").Get()
        textures.append({"path": asset.path, "resolved": bool(asset.resolvedPath)})
result["bound"] = bound
result["textures"] = textures
if usdz:
    result["usdz_written"] = bool(UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(path), usdz))
print("RESULT " + json.dumps(result))
'''


def katana_check(usd_path, usdz_path=""):
    env = dict(os.environ)
    env["PATH"] = os.path.join(KATANA, "bin") + os.pathsep + env.get("PATH", "")
    env["PYTHONPATH"] = os.path.join(KATANA, "bin", "python")
    completed = subprocess.run(
        [os.path.join(KATANA, "bin", "python.exe"), "-c", KATANA_CHECK, usd_path, usdz_path],
        capture_output=True, text=True, env=env, timeout=300, check=False,
    )
    lines = [l for l in completed.stdout.splitlines() if l.startswith("RESULT ")]
    if not lines:
        print(completed.stdout[-1500:], completed.stderr[-1500:])
        raise SystemExit("Katana's USD library could not read %s" % usd_path)
    return json.loads(lines[-1][7:])


MAYA_CHECK = r'''
import json, sys
import maya.standalone
maya.standalone.initialize()
import maya.cmds as cmds
cmds.loadPlugin("mayaUsdPlugin", quiet=True)
cmds.mayaUSDImport(file=sys.argv[1].replace("\\", "/"), shadingMode=[("useRegistry", "UsdPreviewSurface")])
meshes = cmds.ls(type="mesh", noIntermediate=True, long=True)
box = cmds.exactWorldBoundingBox(meshes) if meshes else []
files = [cmds.getAttr(f + ".fileTextureName") for f in cmds.ls(type="file")]
print("RESULT " + json.dumps({
    "meshes": len(meshes), "faces": sum(cmds.polyEvaluate(m, face=True) for m in meshes),
    "uv_sets": [cmds.polyUVSet(m, query=True, allUVSets=True) for m in meshes],
    "bbox": box, "file_nodes": files,
    "shading_groups": sorted({sg for m in meshes for sg in (cmds.listConnections(m, type="shadingEngine") or [])}),
}))
'''


MAYA_WRITE_FBX = r'''
import sys
import maya.standalone
maya.standalone.initialize()
import maya.cmds as cmds
cmds.loadPlugin("fbxmaya", quiet=True)
cube = cmds.polyCube(width=30, height=20, depth=10, name="fbxBox")[0]
cmds.move(0, 10, 0, cube)
cmds.select(cube)
cmds.file(sys.argv[1].replace("\\", "/"), force=True, exportSelected=True, type="FBX export")
print("WROTE")
'''


def mayapy(script, *arguments, timeout=600):
    completed = subprocess.run([MAYAPY, "-c", script] + list(arguments), capture_output=True, text=True,
                               timeout=timeout, check=False)
    lines = [l for l in completed.stdout.splitlines() if l.startswith("RESULT ")]
    return (json.loads(lines[-1][7:]) if lines else None), completed


if os.path.exists(WORK):
    shutil.rmtree(WORK)
os.makedirs(WORK)

# ---- 1. GLB
glb = os.path.join(WORK, "generated.glb")
write_test_glb(glb)
usd = os.path.join(WORK, "glb", "testProp_v001.usd")
info = mesh_to_usd.convert(glb, usd)
print("     ", {k: info[k] for k in ("meshes", "points", "faces", "materials", "textures", "has_uvs", "size_cm")})
check("two placements of the cube became two meshes", info["meshes"] == 2 and info["points"] == 48 and info["faces"] == 24)
check("the material and both textures came across", info["materials"] == 1 and len(info["textures"]) == 2)
check("the textures were written next to the USD",
      all(os.path.exists(os.path.join(os.path.dirname(usd), t)) for t in info["textures"]))
check("UVs were kept", info["has_uvs"])
# small cube: x 0.75..1.25 m; turned cube: x -1.5..-0.5 m; y -0.5..0.5 m; z -0.5..0.5 m
check("node transforms baked and metres turned into cm (%s)" % info["size_cm"],
      np.allclose(info["size_cm"], [275, 100, 100], atol=0.01))

usd_check = katana_check(usd)
print("     ", usd_check)
check("Katana's USD library opens it", usd_check["opened"] and usd_check["meshes"] == 2)
check("default prim, cm and Y up", usd_check["default_prim"] == "testProp_v001"
      and abs(usd_check["meters_per_unit"] - 0.01) < 1e-9 and usd_check["up_axis"] == "Y")
check("bounding box matches (%s .. %s)" % (usd_check["bbox_min"], usd_check["bbox_max"]),
      np.allclose(usd_check["bbox_min"], [-150, -50, -50], atol=0.01) and np.allclose(usd_check["bbox_max"], [125, 50, 50], atol=0.01))
check("every mesh has st and a bound material", all(usd_check["has_st"]) and all(usd_check["bound"]))
check("texture paths resolve", len(usd_check["textures"]) == 2 and all(t["resolved"] for t in usd_check["textures"]))

maya, completed = mayapy(MAYA_CHECK, usd)
if maya is None:
    print(completed.stdout[-1500:], completed.stderr[-1500:])
print("     ", maya)
check("Maya imports it: 2 meshes, 24 faces", maya and maya["meshes"] == 2 and maya["faces"] == 24)
check("each Maya mesh has a UV set", all(maya["uv_sets"]))
check("Maya's bounding box in cm matches", np.allclose(maya["bbox"], [-150, -50, -50, 125, 50, 50], atol=0.01))
check("Maya built the material with a file texture (%s)" % [os.path.basename(f) for f in maya["file_nodes"]],
      any(f.endswith(".png") for f in maya["file_nodes"]) and maya["shading_groups"])

# ---- 2. USDZ
usdz = os.path.join(WORK, "generated.usdz")
katana_check(usd, usdz)
check("Katana packed the converted USD as USDZ", os.path.exists(usdz))
usd_from_usdz = os.path.join(WORK, "usdz", "testPropZ_v001.usd")
mesh_to_usd.convert(usdz, usd_from_usdz)
unpacked = katana_check(usd_from_usdz)
check("USDZ unpacked: same meshes, textures resolve",
      unpacked["meshes"] == 2 and all(t["resolved"] for t in unpacked["textures"]) and len(unpacked["textures"]) == 2)

# ---- 3. FBX through Maya
fbx = os.path.join(WORK, "generated.fbx")
_, completed = mayapy(MAYA_WRITE_FBX, fbx)
check("Maya wrote a test FBX", os.path.exists(fbx))
usd_from_fbx = os.path.join(WORK, "fbx", "testBox_v001.usd")
fbx_info = mesh_to_usd.convert(fbx, usd_from_fbx)
fbx_check = katana_check(usd_from_fbx)
print("     ", fbx_info, fbx_check["bbox_min"], fbx_check["bbox_max"])
check("FBX converted: one mesh with UVs", fbx_info["meshes"] == 1 and fbx_info["has_uvs"] and all(fbx_check["has_st"]))
check("FBX size kept in cm (30 x 20 x 10)", np.allclose(
    np.subtract(fbx_check["bbox_max"], fbx_check["bbox_min"]), [30, 20, 10], atol=0.01))

# ---- refusals
compressed = os.path.join(WORK, "draco.gltf")
with open(compressed, "w") as handle:
    json.dump({"asset": {"version": "2.0"}, "extensionsRequired": ["KHR_draco_mesh_compression"]}, handle)
try:
    mesh_to_usd.convert(compressed, os.path.join(WORK, "draco", "x.usd"))
    refused = False
except mesh_to_usd.ConversionError as error:
    refused = "Draco" in str(error)
check("a Draco-compressed file is refused with a clear message", refused)

# ---- 4. the Griptape node, dry run
os.environ["SG_PIPELINE_REPO"] = REPO
os.environ["SG_PIPELINE_GRIPTAPE_PUBLISH_ROOT"] = os.path.join(WORK, "publish")
spec = importlib.util.spec_from_file_location("sg_pipeline_nodes_3d", os.path.join(REPO, "griptape", "sg_pipeline_nodes_3d.py"))
nodes_3d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nodes_3d)
node = nodes_3d.ShotGridPublish3D("publish3d")
check("a node with no name and no model is refused", len(node.validate_before_node_run() or []) == 2)
for key, value in {"model": glb, "name": "aiProp_model", "entity_type": "Asset", "entity_id": 1412,
                   "description": "sg_pipeline mesh_to_usd self-test", "dry_run": True}.items():
    node.set_parameter_value(key, value)
check("the node validates", not node.validate_before_node_run())
try:
    node.process()
except RuntimeError as error:
    if "expired" in str(error) or "Not signed in" in str(error):
        print("SKIP  node dry run: %s" % error)
        print("\nALL CHECKS PASSED (node dry run skipped)")
        raise SystemExit(0)
    raise
out = node.parameter_output_values
print("     ", out["info"].replace("\n", " | "))
check("dry run: nothing registered", out["new_publish_id"] == 0 and out["info"].startswith("DRY RUN"))
check("the node wrote the USD and kept the source GLB",
      os.path.exists(out["published_path"])
      and os.path.exists(os.path.join(os.path.dirname(out["published_path"]), "source", "generated.glb")))
print("\nALL CHECKS PASSED")
