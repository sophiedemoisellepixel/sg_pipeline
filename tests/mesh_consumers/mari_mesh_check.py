"""
Mari script used by tests/run_mesh_consumers_check.ps1 (mari -x): creates a
project from the USD in SG_PIPELINE_MESH_CHECK_USD the way the loader's
"Create Mari Project" action does, writes the objects and UV patches to
SG_PIPELINE_MESH_CHECK_OUT, then closes and removes the project.
"""

import json
import os
import traceback

import mari

result = {"error": None}
uuid = None
try:
    channel = mari.ChannelInfo("basecolor", 1024, 1024, mari.Image.DEPTH_BYTE)
    mari.projects.create("sg_pipeline_mesh_check", os.environ["SG_PIPELINE_MESH_CHECK_USD"].replace("\\", "/"), [channel])
    project = mari.projects.current()
    uuid = project.uuid()
    result["mari_version"] = mari.app.version().string()
    result["objects"] = [
        {"name": geo.name(), "patches": [patch.udim() for patch in geo.patchList()]} for geo in mari.geo.list()
    ]
except Exception:
    result["error"] = traceback.format_exc()

try:
    if mari.projects.current() is not None:
        mari.projects.close(False)
    if uuid:
        mari.projects.remove(uuid)
except Exception:
    result["cleanup_error"] = traceback.format_exc()

with open(os.environ["SG_PIPELINE_MESH_CHECK_OUT"], "w") as handle:
    json.dump(result, handle, indent=2)
mari.app.quit()
