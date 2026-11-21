"""
USD actions for the Nuke loader (Maya -> Nuke, and Katana -> Nuke for geometry).

Chained after the stock Nuke actions in env/includes/nuke/apps.yml:

    actions_hook: "{self}/tk-nuke_actions.py:{config}/tk-multi-loader2/tk-nuke_actions_usd.py"

Actions:
    nuke_geo_import  GeoImport node: the USD file in Nuke's USD-based 3D system
                     (Nuke 14 and later).
    nuke_read_geo    ReadGeo node: the USD file in the classic 3D system.
"""

import os
import re

import nuke
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

USD_ACTIONS = {
    "nuke_geo_import": {
        "caption": "Create GeoImport Node (USD 3D)",
        "description": "Loads the USD file with a GeoImport node, for Nuke's USD-based 3D system.",
        "node_classes": ["GeoImport"],
    },
    "nuke_read_geo": {
        "caption": "Create ReadGeo Node (Classic 3D)",
        "description": "Loads the USD file with a ReadGeo node, for the classic 3D system.",
        "node_classes": ["ReadGeo2", "ReadGeo"],
    },
}


class NukeUsdActions(HookBaseClass):
    def generate_actions(self, sg_publish_data, actions, ui_area):
        action_instances = super().generate_actions(sg_publish_data, actions, ui_area)
        for name, spec in USD_ACTIONS.items():
            if name in actions:
                action_instances.append(
                    {
                        "name": name,
                        "params": None,
                        "caption": spec["caption"],
                        "description": spec["description"],
                    }
                )
        return action_instances

    def execute_action(self, name, params, sg_publish_data):
        if name not in USD_ACTIONS:
            return super().execute_action(name, params, sg_publish_data)

        path = self.get_publish_path(sg_publish_data)
        if not os.path.exists(path):
            raise Exception("File not found on disk - '%s'" % path)

        node = None
        errors = []
        for node_class in USD_ACTIONS[name]["node_classes"]:
            try:
                node = nuke.createNode(node_class, inpanel=False)
                break
            except RuntimeError as error:
                errors.append("%s: %s" % (node_class, error))
        if node is None:
            raise Exception("This Nuke has no node for this action (%s)." % "; ".join(errors))

        node["file"].fromUserText(path.replace("\\", "/"))
        node.setName(_node_name(sg_publish_data), uncollide=True)
        node["label"].setValue("v%03d" % (sg_publish_data.get("version_number") or 0))
        return node


def _node_name(sg_publish_data):
    """e.g. testAsset_testAsset_model"""
    entity = sg_publish_data.get("entity") or {}
    parts = [entity.get("name"), sg_publish_data.get("name") or sg_publish_data.get("code")]
    name = "_".join(p for p in parts if p) or "usd"
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return name if not name[0].isdigit() else "_%s" % name
