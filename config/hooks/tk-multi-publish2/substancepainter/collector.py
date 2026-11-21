"""
Publisher collector for Substance 3D Painter.

Creates one item for the open Painter project and, under it, one "Texture"
item per texture set and map (base colour, roughness, ...) that the texture
set actually has. publish_textures.py exports and publishes each of them.

    collector: "{self}/collector.py:{config}/tk-multi-publish2/substancepainter/collector.py"
"""

import os

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

SESSION_ITEM_TYPE = "substancepainter.session"
TEXTURE_ITEM_TYPE = "substancepainter.textures"

# map name -> how to export it.
#   channels:  Painter channels (substance_painter.textureset.ChannelType names);
#              the map is offered if the texture set has any of them
#   source:    (srcMapType, srcMapName) for the export configuration
#   color:     RGB if True, single channel (L) otherwise
#   bit_depth: bit depth of the exported png
TEXTURE_MAPS = {
    "basecolor": {"channels": ["BaseColor"], "source": ("documentMap", "basecolor"), "color": True, "bit_depth": "8"},
    "roughness": {"channels": ["Roughness"], "source": ("documentMap", "roughness"), "color": False, "bit_depth": "8"},
    "metallic": {"channels": ["Metallic"], "source": ("documentMap", "metallic"), "color": False, "bit_depth": "8"},
    "normal": {"channels": ["Normal", "Height"], "source": ("virtualMap", "Normal_OpenGL"), "color": True, "bit_depth": "16"},
    "height": {"channels": ["Height"], "source": ("documentMap", "height"), "color": False, "bit_depth": "16"},
    "emissive": {"channels": ["Emissive"], "source": ("documentMap", "emissive"), "color": True, "bit_depth": "8"},
    "opacity": {"channels": ["Opacity"], "source": ("documentMap", "opacity"), "color": False, "bit_depth": "8"},
}


class SubstancePainterCollector(HookBaseClass):
    def process_current_session(self, settings, parent_item):
        import substance_painter.project as sp_project
        import substance_painter.textureset as sp_textureset

        if not sp_project.is_open():
            self.logger.warning("There is no Painter project open, nothing to publish.")
            return

        project_path = sp_project.file_path()
        display_name = os.path.basename(project_path) if project_path else "Unsaved Painter Project"

        session_item = parent_item.create_item(
            SESSION_ITEM_TYPE, "Substance Painter Project", display_name
        )
        session_item.properties["project_path"] = project_path
        self.logger.info("Collected the current Painter project")

        for texture_set in sp_textureset.all_texture_sets():
            if texture_set.is_layered_material():
                self.logger.warning(
                    "Texture set '%s' uses material layering, which is not "
                    "supported yet. Skipping it." % texture_set.name()
                )
                continue

            stack = texture_set.get_stack()
            for map_name, spec in TEXTURE_MAPS.items():
                channel_types = [
                    getattr(sp_textureset.ChannelType, c, None) for c in spec["channels"]
                ]
                if not any(c is not None and stack.has_channel(c) for c in channel_types):
                    continue

                item = session_item.create_item(
                    TEXTURE_ITEM_TYPE,
                    "Texture",
                    "%s %s" % (texture_set.name(), map_name),
                )
                item.properties["texture_set"] = texture_set.name()
                item.properties["texture_map"] = map_name
                item.properties["texture_spec"] = spec
                item.properties["has_uv_tiles"] = texture_set.has_uv_tiles()
