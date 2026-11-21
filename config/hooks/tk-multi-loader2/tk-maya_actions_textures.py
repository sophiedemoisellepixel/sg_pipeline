"""
Texture actions for the Maya loader (Mari -> Maya, and Painter -> Maya).

Chained after the stock and USD actions in env/includes/maya/apps.yml. Both
actions work on "Texture" publishes whose path may contain a <UDIM> token:

    sgp_texture_node    Create a file node for the texture, with UDIM tiling and
                        the right colour space for the kind of map.
    sgp_build_material  Build a standardSurface material from the selected
                        texture publishes and assign it to the selected meshes.
                        Select several publishes in the Loader to get them all
                        in one material.

Texture publishes are named "<prefix>_<map>" ("testMtlSG_basecolor",
"testAsset_model_roughness"). The prefix groups publishes into materials and
the map decides how the texture is connected; see MAPS below.
"""

import glob
import os
import re

import maya.cmds as cmds
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

UDIM_TOKEN = "<UDIM>"
TEXTURE_ACTIONS = ("sgp_texture_node", "sgp_build_material")

# map name -> how it is wired into a standardSurface.
#   color:   True for colour data (uses the scene's default file rule, sRGB),
#            False for data maps, which are read Raw
#   connect: "color" file.outColor -> material.<attr>
#            "alpha" file.outAlpha -> material.<attr> (alpha from luminance)
#            "normal" / "displacement" are handled specially
MAPS = {
    "basecolor": {"color": True, "connect": "color", "attr": "baseColor"},
    "diffuse": {"color": True, "connect": "color", "attr": "baseColor"},
    "roughness": {"color": False, "connect": "alpha", "attr": "specularRoughness"},
    "metallic": {"color": False, "connect": "alpha", "attr": "metalness"},
    "metalness": {"color": False, "connect": "alpha", "attr": "metalness"},
    "emissive": {"color": True, "connect": "color", "attr": "emissionColor"},
    "opacity": {"color": False, "connect": "color", "attr": "opacity"},
    "normal": {"color": False, "connect": "normal"},
    "height": {"color": False, "connect": "displacement"},
    "displacement": {"color": False, "connect": "displacement"},
}


class MayaTextureActions(HookBaseClass):
    def generate_actions(self, sg_publish_data, actions, ui_area):
        action_instances = super().generate_actions(sg_publish_data, actions, ui_area)

        if "sgp_texture_node" in actions:
            action_instances.append(
                {
                    "name": "sgp_texture_node",
                    "params": None,
                    "caption": "Create Texture Node (UDIM)",
                    "description": "Creates a file node for this texture, with UDIM tiling and colour space set.",
                }
            )

        if "sgp_build_material" in actions and map_name_for(sg_publish_data) in MAPS:
            action_instances.append(
                {
                    "name": "sgp_build_material",
                    "params": None,
                    "caption": "Build Material from Textures",
                    "description": "Builds a standardSurface from the selected textures and assigns it to the selected meshes.",
                }
            )

        return action_instances

    def execute_multiple_actions(self, actions):
        # all the textures picked for "Build Material" go into materials together
        material_publishes = [
            a["sg_publish_data"] for a in actions if a["name"] == "sgp_build_material"
        ]
        if material_publishes:
            self.build_materials(material_publishes)

        others = [a for a in actions if a["name"] != "sgp_build_material"]
        if others:
            super().execute_multiple_actions(others)

    def execute_action(self, name, params, sg_publish_data):
        if name not in TEXTURE_ACTIONS:
            return super().execute_action(name, params, sg_publish_data)

        if name == "sgp_texture_node":
            return self.create_file_node(sg_publish_data)
        return self.build_materials([sg_publish_data])

    # ---- file nodes

    def create_file_node(self, sg_publish_data):
        """A file node (with its place2dTexture) for a texture publish."""
        path = self.get_publish_path(sg_publish_data)
        is_udim = UDIM_TOKEN in path
        tiles = sorted(glob.glob(path.replace(UDIM_TOKEN, "[0-9][0-9][0-9][0-9]")))
        if not tiles:
            raise Exception("No texture files found on disk for '%s'" % path)

        name = _node_name(sg_publish_data.get("name") or "texture")
        file_node = cmds.shadingNode("file", asTexture=True, isColorManaged=True, name="%s_file" % name)
        place = cmds.shadingNode("place2dTexture", asUtility=True, name="%s_place2d" % name)
        cmds.connectAttr("%s.outUV" % place, "%s.uvCoord" % file_node)
        cmds.connectAttr("%s.outUvFilterSize" % place, "%s.uvFilterSize" % file_node)

        # Maya works out the tile pattern from the path of one existing tile
        cmds.setAttr("%s.fileTextureName" % file_node, tiles[0].replace("\\", "/"), type="string")
        if is_udim:
            cmds.setAttr("%s.uvTilingMode" % file_node, 3)  # UDIM (Mari)

        spec = MAPS.get(map_name_for(sg_publish_data))
        if spec and not spec["color"]:
            _set_raw(file_node)
            cmds.setAttr("%s.alphaIsLuminance" % file_node, True)

        return file_node

    # ---- materials

    def build_materials(self, publishes):
        """
        One standardSurface per "<prefix>" among the publishes. Returns the
        list of materials created.
        """
        meshes = cmds.ls(selection=True, dagObjects=True, type="mesh", noIntermediate=True, long=True)

        groups = {}
        for sg_publish_data in publishes:
            if map_name_for(sg_publish_data) not in MAPS:
                self.parent.logger.warning(
                    "Don't know how to connect '%s', skipping it." % sg_publish_data.get("name")
                )
                continue
            groups.setdefault(prefix_for(sg_publish_data), []).append(sg_publish_data)

        materials = []
        for prefix, group in groups.items():
            name = _node_name(prefix)
            material = cmds.shadingNode("standardSurface", asShader=True, name="%s_mtl" % name)
            shading_group = cmds.sets(
                renderable=True, noSurfaceShader=True, empty=True, name="%s_SG" % name
            )
            cmds.connectAttr("%s.outColor" % material, "%s.surfaceShader" % shading_group)

            for sg_publish_data in group:
                file_node = self.create_file_node(sg_publish_data)
                self._connect(file_node, MAPS[map_name_for(sg_publish_data)], material, shading_group, name)

            if meshes:
                cmds.sets(meshes, edit=True, forceElement=shading_group)
            materials.append(material)
            self.parent.logger.info(
                "Built %s from %d texture(s)%s"
                % (material, len(group), ", assigned to %d mesh(es)" % len(meshes) if meshes else "")
            )

        if materials:
            cmds.select(materials, replace=True)
        return materials

    def _connect(self, file_node, spec, material, shading_group, name):
        kind = spec["connect"]
        if kind == "color":
            cmds.connectAttr("%s.outColor" % file_node, "%s.%s" % (material, spec["attr"]), force=True)
            if spec["attr"] == "emissionColor":
                cmds.setAttr("%s.emission" % material, 1.0)
        elif kind == "alpha":
            cmds.connectAttr("%s.outAlpha" % file_node, "%s.%s" % (material, spec["attr"]), force=True)
        elif kind == "normal":
            bump = cmds.shadingNode("bump2d", asUtility=True, name="%s_normal_bump2d" % name)
            cmds.setAttr("%s.bumpInterp" % bump, 1)  # tangent space normals
            cmds.connectAttr("%s.outAlpha" % file_node, "%s.bumpValue" % bump)
            cmds.connectAttr("%s.outNormal" % bump, "%s.normalCamera" % material, force=True)
        elif kind == "displacement":
            displacement = cmds.shadingNode(
                "displacementShader", asShader=True, name="%s_displacement" % name
            )
            cmds.connectAttr("%s.outAlpha" % file_node, "%s.displacement" % displacement)
            cmds.connectAttr(
                "%s.displacement" % displacement, "%s.displacementShader" % shading_group, force=True
            )


def map_name_for(sg_publish_data):
    """ "testMtlSG_basecolor" -> "basecolor" """
    name = (sg_publish_data.get("name") or sg_publish_data.get("code") or "").split(".")[0]
    return name.rsplit("_", 1)[-1].lower()


def prefix_for(sg_publish_data):
    """ "testMtlSG_basecolor" -> "testMtlSG" """
    name = (sg_publish_data.get("name") or sg_publish_data.get("code") or "").split(".")[0]
    return name.rsplit("_", 1)[0] if "_" in name else name


def _set_raw(file_node):
    """Read the file without any colour transform."""
    cmds.setAttr("%s.ignoreColorSpaceFileRules" % file_node, True)
    for colorspace in ("Raw", "raw", "Utility - Raw"):
        try:
            cmds.setAttr("%s.colorSpace" % file_node, colorspace, type="string")
            return
        except Exception:
            continue


def _node_name(name):
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return name if not name[:1].isdigit() else "_%s" % name
