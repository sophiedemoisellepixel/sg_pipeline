"""
Publisher collector for Katana (Katana -> Nuke).

Creates one item for the open Katana project and, under it, one "Rendered
Image" item per Render node output that is written to a file and has frames on
disk. publish_render.py publishes each of them.

    collector: "{self}/collector.py:{config}/tk-multi-publish2/katana/collector.py"
"""

import glob
import os
import re

import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

SESSION_ITEM_TYPE = "katana.session"
RENDER_ITEM_TYPE = "katana.render"
# user parameter the loader puts on the nodes it creates (see tk-katana_actions.py)
PUBLISH_ID_PARAMETER = "sgPublishId"


class KatanaCollector(HookBaseClass):
    def process_current_session(self, settings, parent_item):
        from Katana import NodegraphAPI, Nodes3DAPI

        project_path = NodegraphAPI.GetProjectFile() or ""
        display_name = os.path.basename(project_path) if project_path else "Untitled Katana Project"
        session_item = parent_item.create_item(SESSION_ITEM_TYPE, "Katana Project", display_name)
        session_item.properties["path"] = os.path.normpath(project_path) if project_path else None
        session_item.properties["source_publish_ids"] = source_publish_ids()
        self.logger.info("Collected the current Katana project")

        frame = int(NodegraphAPI.GetCurrentTime())
        for node in NodegraphAPI.GetAllNodesByType("Render"):
            if node.isBypassed():
                continue
            try:
                info = Nodes3DAPI.RenderNodeUtil.GetRenderNodeInfo(node)
                output_names = info.getAllOutputNames()
            except Exception as error:
                self.logger.warning("Could not read the outputs of %s: %s" % (node.getName(), error))
                continue

            for output_name in output_names:
                output = info.getOutputInfoByName(output_name, False)
                output_file = output.get("outputFile")
                # outputs rendered to Katana's temporary folder are not publishable
                if not output.get("enabled") or not output_file or _is_temporary(output_file):
                    continue

                sequence_path, frame_files = sequence_for(output_file, frame)
                if not frame_files:
                    self.logger.info(
                        "%s %s: nothing rendered yet at %s" % (node.getName(), output_name, sequence_path)
                    )
                    continue

                item = session_item.create_item(
                    RENDER_ITEM_TYPE, "Rendered Image", "%s %s" % (node.getName(), output_name)
                )
                item.properties["render_node"] = node.getName()
                item.properties["output_name"] = output_name
                item.properties["sequence_path"] = sequence_path
                item.properties["sequence_paths"] = frame_files
                item.properties["source_publish_ids"] = session_item.properties["source_publish_ids"]
                self.logger.info(
                    "Collected %d frame(s) of %s %s" % (len(frame_files), node.getName(), output_name)
                )


def sequence_for(output_file, frame):
    """
    Turn the file Katana writes at `frame` into a sequence path and the frames
    of it that exist on disk:

        .../beauty.0012.exr, 12 -> (.../beauty.%04d.exr, [.../beauty.0001.exr, ...])

    A path without the frame number in it is a single file.
    """
    output_file = os.path.normpath(output_file)
    folder, name = os.path.split(output_file)
    # the last run of digits in the name that equals the frame number
    matches = [m for m in re.finditer(r"\d+", name) if int(m.group()) == frame]
    if not matches:
        return output_file, ([output_file] if os.path.exists(output_file) else [])

    match = matches[-1]
    padding = len(match.group())
    head, tail = name[: match.start()], name[match.end():]
    sequence_path = os.path.join(folder, "%s%%0%dd%s" % (head, padding, tail))
    pattern = os.path.join(folder, glob.escape(head) + "[0-9]" * padding + glob.escape(tail))
    return sequence_path, sorted(glob.glob(pattern))


def source_publish_ids():
    """Ids of the publishes the loader brought into this project."""
    from Katana import NodegraphAPI

    ids = set()
    for node in NodegraphAPI.GetAllNodes():
        parameter = node.getParameter(PUBLISH_ID_PARAMETER)
        if parameter is not None:
            try:
                ids.add(int(parameter.getValue(0)))
            except Exception:
                pass
    return sorted(ids)


def _is_temporary(path):
    return "katana_tmpdir" in path.replace("\\", "/")
