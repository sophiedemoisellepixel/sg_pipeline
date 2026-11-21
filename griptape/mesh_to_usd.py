"""
Turns a generated 3D model (Rodin, Tripo, or any GLB/glTF/USDZ/FBX/OBJ file)
into a USD file the pipeline can publish as "USD Geometry".

    convert(source, target_usd) -> info dict

    .glb / .gltf   read here (pure Python + numpy): every triangle primitive
                   becomes a USD Mesh with points, normals and UVs (primvars:st),
                   node transforms are baked in, and the PBR material becomes a
                   UsdPreviewSurface whose textures are written next to the USD
                   (textures/...). Draco or meshopt compressed files are refused.
    .usdz          unpacked next to the target; the package's root layer is
                   renamed to the target, its textures keep their relative paths.
    .usd/.usda/.usdc  copied.
    .fbx / .obj    converted by Maya (mayapy): imported, then exported with
                   mayaUSDExport like the Maya publisher does.

The USD is written in centimetres (metersPerUnit 0.01, Y up), the units
Maya, Painter and Katana use here; glTF files are in metres, so 1 glTF unit
becomes 100 cm. `scale` multiplies on top of that.

Command line, for tests:

    python mesh_to_usd.py <source> <target.usd> [--scale 1.0]
"""

import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile

MAYAPY = os.environ.get("SG_PIPELINE_MAYAPY", r"C:\Program Files\Autodesk\Maya2026\bin\mayapy.exe")
UNSUPPORTED_EXTENSIONS = {
    "KHR_draco_mesh_compression": "Draco compression",
    "EXT_meshopt_compression": "meshopt compression",
}
GLTF_TO_CM = 100.0


class ConversionError(RuntimeError):
    pass


def convert(source, target, scale=1.0):
    """Convert `source` to the USD file `target`. Returns what was written."""
    extension = os.path.splitext(source)[1].lower()
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    if extension in (".glb", ".gltf"):
        info = gltf_to_usd(source, target, scale)
    elif extension == ".usdz":
        info = usdz_to_usd(source, target)
    elif extension in (".usd", ".usda", ".usdc"):
        shutil.copyfile(source, target)
        info = {"meshes": None, "warnings": ["USD copied as it is; files it references were not copied."]}
    elif extension in (".fbx", ".obj"):
        info = maya_to_usd(source, target, scale)
    else:
        raise ConversionError("Cannot turn a %s file into USD (GLB, glTF, USDZ, USD, FBX or OBJ)." % extension)
    info.setdefault("warnings", [])
    info["usd"] = os.path.abspath(target)
    info["source_format"] = extension.lstrip(".")
    return info


# ---------------------------------------------------------------- glTF


COMPONENTS = {5120: "<i1", 5121: "<u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
NORMALIZE = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}
SIZES = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
IMAGE_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/ktx2": ".ktx2"}


class Gltf:
    """The parts of a glTF 2.0 file the conversion needs."""

    def __init__(self, path):
        import numpy

        self.np = numpy
        self.folder = os.path.dirname(os.path.abspath(path))
        with open(path, "rb") as handle:
            data = handle.read()
        binary = None
        if data[:4] == b"glTF":
            version, length = struct.unpack_from("<II", data, 4)
            if version != 2:
                raise ConversionError("Only glTF 2.0 is supported (this file is version %d)." % version)
            offset, document = 12, None
            while offset < min(length, len(data)):
                chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
                chunk = data[offset + 8: offset + 8 + chunk_length]
                if chunk_type == 0x4E4F534A:
                    document = json.loads(chunk.decode("utf-8"))
                elif chunk_type == 0x004E4942:
                    binary = chunk
                offset += 8 + chunk_length
            if document is None:
                raise ConversionError("The GLB file has no JSON chunk.")
        else:
            document = json.loads(data.decode("utf-8-sig"))
        self.doc = document

        required = set(document.get("extensionsRequired") or [])
        refused = [UNSUPPORTED_EXTENSIONS[e] for e in required if e in UNSUPPORTED_EXTENSIONS]
        if refused:
            raise ConversionError(
                "The model uses %s, which this converter cannot read. Export it again without "
                "compression (or ask Rodin for USDZ)." % " and ".join(refused)
            )
        self.ignored_extensions = sorted(required - set(UNSUPPORTED_EXTENSIONS))

        self.buffers = []
        for index, buffer in enumerate(document.get("buffers") or []):
            uri = buffer.get("uri")
            if uri is None:
                if binary is None:
                    raise ConversionError("Buffer %d has no data." % index)
                self.buffers.append(binary)
            else:
                self.buffers.append(self._read_uri(uri))

    def _read_uri(self, uri):
        if uri.startswith("data:"):
            return base64.b64decode(uri.split(",", 1)[1])
        from urllib.parse import unquote

        with open(os.path.join(self.folder, unquote(uri)), "rb") as handle:
            return handle.read()

    def view_bytes(self, index):
        view = self.doc["bufferViews"][index]
        start = view.get("byteOffset", 0)
        return self.buffers[view["buffer"]][start: start + view["byteLength"]]

    def accessor(self, index):
        """An accessor as a float or int numpy array of shape (count, size)."""
        np = self.np
        accessor = self.doc["accessors"][index]
        size = SIZES[accessor["type"]]
        component = accessor["componentType"]
        dtype = np.dtype(COMPONENTS[component])
        count = accessor["count"]
        if "bufferView" in accessor:
            view = self.doc["bufferViews"][accessor["bufferView"]]
            buffer = self.buffers[view["buffer"]]
            offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            stride = view.get("byteStride") or dtype.itemsize * size
            array = np.ndarray(
                shape=(count, size), dtype=dtype, buffer=buffer, offset=offset,
                strides=(stride, dtype.itemsize),
            ).copy()
        else:
            array = np.zeros((count, size), dtype=dtype)
        if "sparse" in accessor:
            sparse = accessor["sparse"]
            indices = self._raw(sparse["indices"], sparse["count"], 1).reshape(-1)
            values = self._raw(dict(sparse["values"], componentType=component), sparse["count"], size)
            array[indices] = values
        if accessor.get("normalized") and component in NORMALIZE:
            array = np.maximum(array.astype(np.float64) / NORMALIZE[component], -1.0)
        return array

    def _raw(self, spec, count, size):
        np = self.np
        dtype = np.dtype(COMPONENTS[spec["componentType"]])
        data = self.view_bytes(spec["bufferView"])
        return np.frombuffer(data, dtype=dtype, count=count * size, offset=spec.get("byteOffset", 0)).reshape(count, size)

    def image(self, index):
        """(bytes, extension, name) of an image."""
        image = self.doc["images"][index]
        if "bufferView" in image:
            data = self.view_bytes(image["bufferView"])
            extension = IMAGE_EXTENSIONS.get(image.get("mimeType"), ".png")
        else:
            uri = image["uri"]
            data = self._read_uri(uri)
            if uri.startswith("data:"):
                extension = IMAGE_EXTENSIONS.get(uri[5:].split(";", 1)[0], ".png")
            else:
                extension = os.path.splitext(uri)[1].lower() or ".png"
        return data, extension, image.get("name") or "image_%d" % index

    def world_matrices(self):
        """(mesh index, node name, 4x4 world matrix) for every node with a mesh."""
        np = self.np
        nodes = self.doc.get("nodes") or []
        scenes = self.doc.get("scenes") or []
        if scenes:
            roots = scenes[self.doc.get("scene", 0)].get("nodes") or []
        else:
            children = {c for n in nodes for c in n.get("children") or []}
            roots = [i for i in range(len(nodes)) if i not in children]

        found = []

        def visit(index, parent):
            node = nodes[index]
            world = parent @ local_matrix(np, node)
            if "mesh" in node:
                found.append((node["mesh"], node.get("name") or "node_%d" % index, world))
            for child in node.get("children") or []:
                visit(child, world)

        for root in roots:
            visit(root, np.identity(4))
        if not found and self.doc.get("meshes"):
            # meshes not placed in any scene
            found = [(i, "mesh_%d" % i, np.identity(4)) for i in range(len(self.doc["meshes"]))]
        return found


def local_matrix(np, node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T  # glTF is column-major
    translation = np.identity(4)
    translation[:3, 3] = node.get("translation", [0, 0, 0])
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    rotation = np.identity(4)
    rotation[:3, :3] = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    scaling = np.diag(list(node.get("scale", [1, 1, 1])) + [1])
    return translation @ rotation @ scaling


def gltf_to_usd(source, target, scale=1.0):
    gltf = Gltf(source)
    np = gltf.np
    doc = gltf.doc
    root_name = usd_name(os.path.splitext(os.path.basename(target))[0])
    texture_folder = os.path.join(os.path.dirname(os.path.abspath(target)), "textures")
    unit = GLTF_TO_CM * float(scale or 1.0)

    warnings = []
    if gltf.ignored_extensions:
        warnings.append("Ignored glTF extensions: %s" % ", ".join(gltf.ignored_extensions))

    written_images = {}

    def texture_file(texture_info):
        """Write a texture's image next to the USD once; its path relative to the USD."""
        if not texture_info:
            return None
        texture = doc["textures"][texture_info["index"]]
        source_index = texture.get("source")
        if source_index is None:
            # e.g. a webp or ktx2 image only reachable through an extension
            extension_sources = [v.get("source") for v in (texture.get("extensions") or {}).values()]
            source_index = next((s for s in extension_sources if s is not None), None)
        if source_index is None:
            return None
        if texture_info.get("texCoord", 0) != 0:
            warnings.append("A texture uses a second UV set; it was mapped on the first one.")
        if source_index not in written_images:
            data, extension, name = gltf.image(source_index)
            os.makedirs(texture_folder, exist_ok=True)
            file_name = "%s_%d%s" % (usd_name(name), source_index, extension)
            with open(os.path.join(texture_folder, file_name), "wb") as handle:
                handle.write(data)
            written_images[source_index] = "./textures/" + file_name
        return written_images[source_index]

    meshes = []
    used_materials = set()
    for mesh_index, node_name, world in gltf.world_matrices():
        mesh = doc["meshes"][mesh_index]
        for primitive_index, primitive in enumerate(mesh.get("primitives") or []):
            mode = primitive.get("mode", 4)
            attributes = primitive.get("attributes") or {}
            if "POSITION" not in attributes:
                continue
            points = gltf.accessor(attributes["POSITION"]).astype(np.float64)
            if "indices" in primitive:
                indices = gltf.accessor(primitive["indices"]).reshape(-1).astype(np.int64)
            else:
                indices = np.arange(len(points), dtype=np.int64)
            triangles = triangulate(np, indices, mode)
            if triangles is None:
                warnings.append("Skipped a primitive drawn as points or lines (mode %d)." % mode)
                continue

            homogeneous = np.hstack([points, np.ones((len(points), 1))])
            points = (homogeneous @ world.T)[:, :3] * unit
            if np.linalg.det(world[:3, :3]) < 0:
                triangles = triangles[:, ::-1]  # a mirroring transform flips the winding

            normals = None
            if "NORMAL" in attributes:
                normal_matrix = np.linalg.inv(world[:3, :3]).T
                normals = gltf.accessor(attributes["NORMAL"]).astype(np.float64) @ normal_matrix.T
                lengths = np.linalg.norm(normals, axis=1, keepdims=True)
                normals = normals / np.where(lengths == 0, 1, lengths)

            st = None
            if "TEXCOORD_0" in attributes:
                st = gltf.accessor(attributes["TEXCOORD_0"]).astype(np.float64)
                st = np.column_stack([st[:, 0], 1.0 - st[:, 1]])  # glTF V runs down

            material_index = primitive.get("material")
            if material_index is not None:
                used_materials.add(material_index)
            base = usd_name("%s_%s" % (node_name, mesh.get("name") or "mesh_%d" % mesh_index))
            name = base if len(mesh.get("primitives")) == 1 else "%s_%d" % (base, primitive_index)
            meshes.append({
                "name": name, "points": points, "triangles": triangles, "normals": normals,
                "st": st, "material": material_index,
            })

    if not meshes:
        raise ConversionError("The model has no triangle meshes.")

    names = unique_names([m["name"] for m in meshes])
    for mesh, name in zip(meshes, names):
        mesh["name"] = name

    materials = {}
    for material_index in sorted(used_materials):
        material = (doc.get("materials") or [])[material_index]
        pbr = material.get("pbrMetallicRoughness") or {}
        materials[material_index] = {
            "name": usd_name(material.get("name") or "material_%d" % material_index),
            "base_color": (pbr.get("baseColorFactor") or [1, 1, 1, 1])[:3],
            "opacity": (pbr.get("baseColorFactor") or [1, 1, 1, 1])[3],
            "metallic": pbr.get("metallicFactor", 1.0),
            "roughness": pbr.get("roughnessFactor", 1.0),
            "emissive": material.get("emissiveFactor") or [0, 0, 0],
            "base_color_texture": texture_file(pbr.get("baseColorTexture")),
            "metallic_roughness_texture": texture_file(pbr.get("metallicRoughnessTexture")),
            "normal_texture": texture_file(material.get("normalTexture")),
            "emissive_texture": texture_file(material.get("emissiveTexture")),
            "alpha_mode": material.get("alphaMode", "OPAQUE"),
        }
    material_names = unique_names([m["name"] for m in materials.values()])
    for material, name in zip(materials.values(), material_names):
        material["name"] = name

    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        write_usda(handle, root_name, meshes, materials)

    all_points = np.vstack([m["points"] for m in meshes])
    return {
        "meshes": len(meshes),
        "points": int(sum(len(m["points"]) for m in meshes)),
        "faces": int(sum(len(m["triangles"]) for m in meshes)),
        "materials": len(materials),
        "textures": sorted(written_images.values()),
        "has_uvs": all(m["st"] is not None for m in meshes),
        "size_cm": [round(float(v), 3) for v in all_points.max(axis=0) - all_points.min(axis=0)],
        "warnings": warnings,
    }


def triangulate(np, indices, mode):
    if mode == 4:
        return indices[: len(indices) // 3 * 3].reshape(-1, 3)
    if mode == 5:  # strip
        tris = [
            (indices[i], indices[i + 1], indices[i + 2]) if i % 2 == 0 else (indices[i + 1], indices[i], indices[i + 2])
            for i in range(len(indices) - 2)
        ]
        return np.array(tris, dtype=np.int64).reshape(-1, 3)
    if mode == 6:  # fan
        tris = [(indices[0], indices[i], indices[i + 1]) for i in range(1, len(indices) - 1)]
        return np.array(tris, dtype=np.int64).reshape(-1, 3)
    return None


def usd_name(name):
    name = re.sub(r"[^A-Za-z0-9_]", "_", name or "") or "item"
    return name if not name[0].isdigit() else "_" + name


def unique_names(names):
    seen, result = {}, []
    for name in names:
        if name in seen:
            seen[name] += 1
            result.append("%s_%d" % (name, seen[name]))
        else:
            seen[name] = 0
            result.append(name)
    return result


def _vectors(rows, kind):
    if kind == "int":
        return "[" + ", ".join(str(int(v)) for v in rows) + "]"
    return "[" + ", ".join("(" + ", ".join("%.6g" % c for c in row) + ")" for row in rows) + "]"


def write_usda(out, root, meshes, materials):
    out.write('#usda 1.0\n(\n    defaultPrim = "%s"\n    metersPerUnit = 0.01\n    upAxis = "Y"\n'
              '    doc = "Converted by sg_pipeline griptape/mesh_to_usd.py"\n)\n\n' % root)
    out.write('def Xform "%s" (\n    kind = "component"\n)\n{\n' % root)
    out.write('    def Scope "geo"\n    {\n')
    for mesh in meshes:
        points, triangles = mesh["points"], mesh["triangles"]
        lower, upper = points.min(axis=0), points.max(axis=0)
        schemas = (
            ' (\n            prepend apiSchemas = ["MaterialBindingAPI"]\n        )'
            if mesh["material"] is not None else ""
        )
        out.write('        def Mesh "%s"%s\n        {\n' % (mesh["name"], schemas))
        out.write("            float3[] extent = %s\n" % _vectors([lower, upper], "float"))
        out.write("            int[] faceVertexCounts = %s\n" % ("[" + ", ".join(["3"] * len(triangles)) + "]"))
        out.write("            int[] faceVertexIndices = %s\n" % _vectors(triangles.reshape(-1), "int"))
        out.write("            point3f[] points = %s\n" % _vectors(points, "float"))
        if mesh["normals"] is not None:
            out.write('            normal3f[] normals = %s (\n                interpolation = "vertex"\n            )\n'
                      % _vectors(mesh["normals"], "float"))
        if mesh["st"] is not None:
            # faceVarying with indices, like Maya writes it: Mari hangs loading
            # vertex-interpolated UVs
            out.write('            texCoord2f[] primvars:st = %s (\n                interpolation = "faceVarying"\n            )\n'
                      % _vectors(mesh["st"], "float"))
            out.write("            int[] primvars:st:indices = %s\n" % _vectors(triangles.reshape(-1), "int"))
        out.write('            uniform token subdivisionScheme = "none"\n')
        if mesh["material"] is not None:
            out.write("            rel material:binding = </%s/mtl/%s>\n" % (root, materials[mesh["material"]]["name"]))
        out.write("        }\n")
    out.write("    }\n")

    if materials:
        out.write('\n    def Scope "mtl"\n    {\n')
        for material in materials.values():
            write_material(out, "/%s/mtl/%s" % (root, material["name"]), material)
        out.write("    }\n")
    out.write("}\n")


def write_material(out, path, material):
    name = path.rsplit("/", 1)[-1]
    surface = path + "/surface"
    out.write('        def Material "%s"\n        {\n' % name)
    out.write("            token outputs:surface.connect = <%s.outputs:surface>\n\n" % surface)

    textures = []
    lines = ['                uniform token info:id = "UsdPreviewSurface"']
    if material["base_color_texture"]:
        textures.append(("basecolor_tex", material["base_color_texture"], "sRGB"))
        lines.append("                color3f inputs:diffuseColor.connect = <%s/basecolor_tex.outputs:rgb>" % path)
    else:
        lines.append("                color3f inputs:diffuseColor = (%s)" % ", ".join("%.6g" % c for c in material["base_color"]))
    if material["metallic_roughness_texture"]:
        # glTF packs roughness in green and metallic in blue
        textures.append(("metal_rough_tex", material["metallic_roughness_texture"], "raw"))
        lines.append("                float inputs:roughness.connect = <%s/metal_rough_tex.outputs:g>" % path)
        lines.append("                float inputs:metallic.connect = <%s/metal_rough_tex.outputs:b>" % path)
    else:
        lines.append("                float inputs:roughness = %.6g" % material["roughness"])
        lines.append("                float inputs:metallic = %.6g" % material["metallic"])
    if material["normal_texture"]:
        textures.append(("normal_tex", material["normal_texture"], "raw"))
        lines.append("                normal3f inputs:normal.connect = <%s/normal_tex.outputs:rgb>" % path)
    if material["emissive_texture"]:
        textures.append(("emissive_tex", material["emissive_texture"], "sRGB"))
        lines.append("                color3f inputs:emissiveColor.connect = <%s/emissive_tex.outputs:rgb>" % path)
    elif any(material["emissive"]):
        lines.append("                color3f inputs:emissiveColor = (%s)" % ", ".join("%.6g" % c for c in material["emissive"]))
    if material["alpha_mode"] != "OPAQUE" and material["opacity"] < 1:
        lines.append("                float inputs:opacity = %.6g" % material["opacity"])
    lines.append("                token outputs:surface")
    out.write('            def Shader "surface"\n            {\n' + "\n".join(lines) + "\n            }\n")

    if textures:
        out.write('\n            def Shader "st_reader"\n            {\n'
                  '                uniform token info:id = "UsdPrimvarReader_float2"\n'
                  '                string inputs:varname = "st"\n'
                  "                float2 outputs:result\n            }\n")
    for shader_name, file_path, color_space in textures:
        extra = ""
        if shader_name == "normal_tex":
            # stored 0..1, used -1..1
            extra = ("                float4 inputs:scale = (2, 2, 2, 1)\n"
                     "                float4 inputs:bias = (-1, -1, -1, 0)\n")
        out.write(
            '\n            def Shader "%s"\n            {\n'
            '                uniform token info:id = "UsdUVTexture"\n'
            "                asset inputs:file = @%s@\n"
            '                token inputs:sourceColorSpace = "%s"\n'
            "                float2 inputs:st.connect = <%s/st_reader.outputs:result>\n"
            '                token inputs:wrapS = "repeat"\n'
            '                token inputs:wrapT = "repeat"\n'
            "%s"
            "                float3 outputs:rgb\n"
            "                float outputs:g\n"
            "                float outputs:b\n"
            "            }\n" % (shader_name, file_path, color_space, path, extra)
        )
    out.write("        }\n")


# ---------------------------------------------------------------- USDZ


def usdz_to_usd(source, target):
    """Unpack the package next to the target and rename its root layer."""
    folder = os.path.dirname(os.path.abspath(target))
    with zipfile.ZipFile(source) as package:
        names = package.namelist()
        layers = [n for n in names if os.path.splitext(n)[1].lower() in (".usd", ".usdc", ".usda")]
        if not layers:
            raise ConversionError("The USDZ package has no USD layer in it.")
        root = layers[0]  # the first layer in a USDZ package is its root
        for name in names:
            destination = os.path.normpath(os.path.join(folder, name))
            if not destination.startswith(folder + os.sep):
                raise ConversionError("The USDZ package has a file outside its folder: %s" % name)
        package.extractall(folder)
    extracted_root = os.path.join(folder, root)
    if os.path.dirname(os.path.normpath(root)):
        # the root's relative paths only hold in its own folder
        raise ConversionError("The USDZ root layer %s is not at the top of the package." % root)
    if os.path.abspath(extracted_root) != os.path.abspath(target):
        os.replace(extracted_root, target)
    textures = [n for n in names if n != root and os.path.splitext(n)[1].lower() in (".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff")]
    return {"meshes": None, "textures": textures, "warnings": []}


# ---------------------------------------------------------------- FBX / OBJ through Maya

MAYA_SCRIPT = r'''
import json, sys
import maya.standalone
maya.standalone.initialize()
import maya.cmds as cmds
source, target, scale = sys.argv[1], sys.argv[2], float(sys.argv[3])
for plugin in ("fbxmaya", "objExport", "mayaUsdPlugin"):
    cmds.loadPlugin(plugin, quiet=True)
file_type = "FBX" if source.lower().endswith(".fbx") else "OBJ"
cmds.file(new=True, force=True)
cmds.file(source, i=True, type=file_type, ignoreVersion=True, mergeNamespacesOnClash=False, namespace=":")
roots = [r for r in cmds.ls(assemblies=True, long=True) or []
         if not cmds.listRelatives(r, shapes=True, type="camera")]
if scale != 1.0 and roots:
    group = cmds.group(roots, name="scaled")
    cmds.xform(group, scale=(scale, scale, scale), pivots=(0, 0, 0))
meshes = cmds.ls(type="mesh", noIntermediate=True, long=True)
if not meshes:
    raise SystemExit("no meshes in " + source)
cmds.mayaUSDExport(file=target.replace("\\", "/"), exportUVs=True, exportDisplayColor=False,
                   defaultMeshScheme="none", shadingMode="useRegistry",
                   convertMaterialsTo=["UsdPreviewSurface"], stripNamespaces=True, exportVisibility=True)
faces = sum(cmds.polyEvaluate(m, face=True) for m in meshes)
uvs = all((cmds.polyUVSet(m, query=True, allUVSets=True) or []) for m in meshes)
print("SG_PIPELINE_RESULT " + json.dumps({"meshes": len(meshes), "faces": faces, "has_uvs": uvs}))
'''


def maya_to_usd(source, target, scale=1.0):
    if not os.path.exists(MAYAPY):
        raise ConversionError("FBX and OBJ need Maya, which was not found at %s." % MAYAPY)
    completed = subprocess.run(
        [MAYAPY, "-c", MAYA_SCRIPT, os.path.abspath(source), os.path.abspath(target), str(float(scale or 1.0))],
        capture_output=True, text=True, timeout=900,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
    )
    marker = [line for line in completed.stdout.splitlines() if line.startswith("SG_PIPELINE_RESULT ")]
    if not marker or not os.path.exists(target):
        raise ConversionError("Maya could not convert %s:\n%s" % (
            os.path.basename(source), (completed.stderr or completed.stdout)[-800:]))
    info = json.loads(marker[-1].split(" ", 1)[1])
    info["warnings"] = ["Converted by Maya; units come from the %s file." % os.path.splitext(source)[1]]
    return info


if __name__ == "__main__":
    arguments = sys.argv[1:]
    scale = 1.0
    if "--scale" in arguments:
        at = arguments.index("--scale")
        scale = float(arguments[at + 1])
        del arguments[at: at + 2]
    print(json.dumps(convert(arguments[0], arguments[1], scale), indent=2))
