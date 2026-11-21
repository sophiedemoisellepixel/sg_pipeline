"""
Adds a "USD Geometry" item to the Maya publisher.

Chained after the stock Maya collector in env/includes/maya/apps.yml:

    collector: "{self}/collector.py:{engine}/tk-multi-publish2/basic/collector.py:{config}/tk-multi-publish2/maya/collector_usd.py"

The item is picked up by publish_usd.py, which exports the geometry to USD so
the downstream applications (Substance Painter, Mari, Katana, Nuke) can all
load the same file.
"""

import maya.cmds as cmds
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

USD_ITEM_TYPE = "maya.session.usd"


class MayaUsdCollector(HookBaseClass):
    def process_current_session(self, settings, parent_item):
        # let the stock collector build the session item and its children
        super().process_current_session(settings, parent_item)

        if not cmds.ls(geometry=True, noIntermediate=True):
            return

        session_item = next(
            (i for i in parent_item.children if i.type_spec == "maya.session"), None
        )
        if session_item is None:
            return

        session_item.create_item(USD_ITEM_TYPE, "USD Geometry", "Session Geometry (USD)")
        self.logger.info("Collected session geometry for USD export")
