"""
USD actions for the Maya loader.

Chained after the stock Maya actions in env/includes/maya/apps.yml:

    actions_hook: "{self}/tk-maya_actions.py:{config}/tk-multi-loader2/tk-maya_actions_usd.py"

Actions:
    usd_stage   Reference the file as a USD stage (mayaUsdProxyShape). Nothing is
                converted, the published file stays the source of truth.
    usd_import  Convert the USD file to native Maya nodes.
"""

import os
import re

import maya.cmds as cmds
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

USD_PLUGIN = "mayaUsdPlugin"
USD_ACTIONS = ("usd_stage", "usd_import")


class MayaUsdActions(HookBaseClass):
    def generate_actions(self, sg_publish_data, actions, ui_area):
        action_instances = super().generate_actions(sg_publish_data, actions, ui_area)

        if "usd_stage" in actions:
            action_instances.append(
                {
                    "name": "usd_stage",
                    "params": None,
                    "caption": "Create USD Stage",
                    "description": "References the USD file as a stage (proxy shape) in the scene.",
                }
            )

        if "usd_import" in actions:
            action_instances.append(
                {
                    "name": "usd_import",
                    "params": None,
                    "caption": "Import USD as Maya Geometry",
                    "description": "Converts the USD file to native Maya nodes.",
                }
            )

        return action_instances

    def execute_action(self, name, params, sg_publish_data):
        if name not in USD_ACTIONS:
            return super().execute_action(name, params, sg_publish_data)

        path = self.get_publish_path(sg_publish_data)
        if not os.path.exists(path):
            raise Exception("File not found on disk - '%s'" % path)

        if not cmds.pluginInfo(USD_PLUGIN, query=True, loaded=True):
            cmds.loadPlugin(USD_PLUGIN, quiet=True)

        if name == "usd_stage":
            return self._create_usd_stage(path, sg_publish_data)
        return self._import_usd(path, sg_publish_data)

    def _create_usd_stage(self, path, sg_publish_data):
        """Create a mayaUsdProxyShape pointing at the published file."""
        node_name = _node_name(sg_publish_data)
        transform = cmds.createNode("transform", name=node_name)
        shape = cmds.createNode(
            "mayaUsdProxyShape", name="%sShape" % transform, parent=transform
        )
        cmds.setAttr("%s.filePath" % shape, path.replace("\\", "/"), type="string")
        # drive animated stages from the Maya timeline
        cmds.connectAttr("time1.outTime", "%s.time" % shape)
        cmds.select(transform, replace=True)
        return shape

    def _import_usd(self, path, sg_publish_data):
        """Convert the USD file to Maya nodes, grouped under one transform."""
        before = set(cmds.ls(assemblies=True, long=True))
        cmds.mayaUSDImport(
            file=path.replace("\\", "/"),
            readAnimData=True,
            shadingMode=[("useRegistry", "UsdPreviewSurface")],
        )
        new_roots = [
            n for n in cmds.ls(assemblies=True, long=True) if n not in before
        ]
        if not new_roots:
            return None
        group = cmds.group(new_roots, name=_node_name(sg_publish_data))
        cmds.select(group, replace=True)
        return group


def _node_name(sg_publish_data):
    """e.g. coyote_coyote_model_usd"""
    entity = sg_publish_data.get("entity") or {}
    parts = [entity.get("name"), sg_publish_data.get("name") or sg_publish_data.get("code")]
    name = "_".join(p for p in parts if p) or "usd"
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return name if not name[0].isdigit() else "_%s" % name
