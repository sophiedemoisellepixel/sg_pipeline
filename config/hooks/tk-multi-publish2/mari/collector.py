"""
Publisher collector for Mari.

Creates one item for the open Mari project and, under it, one "Texture" item
per object and channel. publish_channel.py exports and publishes each of them.

    collector: "{self}/collector.py:{config}/tk-multi-publish2/mari/collector.py"
"""

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

SESSION_ITEM_TYPE = "mari.session"
CHANNEL_ITEM_TYPE = "mari.channel"


class MariCollector(HookBaseClass):
    def process_current_session(self, settings, parent_item):
        import mari

        project = mari.projects.current()
        if project is None:
            self.logger.warning("There is no Mari project open, nothing to publish.")
            return

        session_item = parent_item.create_item(
            SESSION_ITEM_TYPE, "Mari Project", project.name()
        )
        self.logger.info("Collected the current Mari project")

        for geo in mari.geo.list():
            # Mari's built-in 2D paint canvas is listed as an object too
            if geo.name().startswith("2D Paint"):
                continue
            for channel in geo.channelList():
                item = session_item.create_item(
                    CHANNEL_ITEM_TYPE, "Texture", "%s %s" % (geo.name(), channel.name())
                )
                item.properties["geo_name"] = geo.name()
                item.properties["channel_name"] = channel.name()
