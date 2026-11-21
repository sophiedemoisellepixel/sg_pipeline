"""
Loader actions for Katana (Maya -> Katana).

Mapped in env/includes/katana/apps.yml:

  USD Geometry
    katana_usd_in    Create a UsdIn node that reads the published USD file.

The id of the publish is stored on the node (user parameter sgPublishId) so
that renders published from the project are linked to the geometry.
"""

import os
import re

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

# read back by the publisher's collector (tk-multi-publish2/katana/collector.py)
PUBLISH_ID_PARAMETER = "sgPublishId"

ACTIONS = {
    "katana_usd_in": (
        "Create UsdIn Node",
        "Creates a UsdIn node that reads this USD file.",
    ),
}


class KatanaActions(HookBaseClass):
    def generate_actions(self, sg_publish_data, actions, ui_area):
        return [
            {
                "name": name,
                "params": None,
                "caption": ACTIONS[name][0],
                "description": ACTIONS[name][1],
            }
            for name in actions
            if name in ACTIONS
        ]

    def execute_multiple_actions(self, actions):
        for single_action in actions:
            self.execute_action(
                single_action["name"],
                single_action["params"],
                single_action["sg_publish_data"],
            )

    def execute_action(self, name, params, sg_publish_data):
        if name not in ACTIONS:
            raise Exception("Unknown action '%s'" % name)

        path = self.get_publish_path(sg_publish_data)
        if not os.path.exists(path):
            raise Exception("File not found on disk - '%s'" % path)
        return self._create_usd_in(path, sg_publish_data)

    def _create_usd_in(self, path, sg_publish_data):
        from Katana import NodegraphAPI

        node = NodegraphAPI.CreateNode("UsdIn", NodegraphAPI.GetRootNode())
        node.setName(_node_name(sg_publish_data))
        node.getParameter("fileName").setValue(path.replace("\\", "/"), 0)
        # remembered so that renders published from this project link back to it
        if sg_publish_data.get("id"):
            node.getParameters().createChildNumber(PUBLISH_ID_PARAMETER, sg_publish_data["id"])

        # place it next to whatever is already in the node graph
        others = [n for n in NodegraphAPI.GetRootNode().getChildren() if n is not node]
        if others:
            positions = [NodegraphAPI.GetNodePosition(n) for n in others]
            NodegraphAPI.SetNodePosition(
                node, (max(p[0] for p in positions) + 200, max(p[1] for p in positions))
            )
        NodegraphAPI.SetAllSelectedNodes([node])
        return node


def _node_name(sg_publish_data):
    """e.g. testAsset_testAsset_model_usd"""
    entity = sg_publish_data.get("entity") or {}
    parts = [entity.get("name"), sg_publish_data.get("name") or sg_publish_data.get("code")]
    name = "_".join(p for p in parts if p) or "usd"
    name = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return name if not name[0].isdigit() else "_%s" % name
