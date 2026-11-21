"""
Painter plug-in used by tests/run_mesh_consumers_check.ps1: creates a project
from the USD in SG_PIPELINE_MESH_CHECK_USD with the same settings as the
loader's "Create Painter Project" action, writes what Painter made of it to
SG_PIPELINE_MESH_CHECK_OUT, and closes Painter. Does nothing unless those are set.
"""

import json
import os
import time
import traceback

USD = os.environ.get("SG_PIPELINE_MESH_CHECK_USD")
OUT = os.environ.get("SG_PIPELINE_MESH_CHECK_OUT")
TIMEOUT = 240

_timer = None
_state = {"started": time.time(), "created": False}


def start_plugin():
    global _timer
    if not (USD and OUT):
        return
    from PySide6 import QtCore

    _timer = QtCore.QTimer()
    _timer.setInterval(1000)
    _timer.timeout.connect(_tick)
    _timer.start()


def close_plugin():
    global _timer
    if _timer is not None:
        _timer.stop()
        _timer = None


def _tick():
    import substance_painter.project as sp_project
    import substance_painter.textureset as sp_textureset

    try:
        if time.time() - _state["started"] > TIMEOUT:
            return _finish({"error": "timed out"})
        if not _state["created"]:
            settings = sp_project.Settings(
                import_cameras=False,
                project_workflow=sp_project.ProjectWorkflow.UVTile,
                mesh_settings=sp_project.UsdSettings(subdivision_level=0),
            )
            sp_project.create(mesh_file_path=USD.replace("\\", "/"), settings=settings)
            _state["created"] = True
            return
        if not sp_project.is_open() or sp_project.is_busy():
            return
        sets = []
        for texture_set in sp_textureset.all_texture_sets():
            tiles = [1001 + tile.u + 10 * tile.v for tile in texture_set.all_uv_tiles()] if texture_set.has_uv_tiles() else [1001]
            sets.append({"name": texture_set.name(), "uv_tiles": tiles})
        _finish({"error": None, "texture_sets": sets})
    except Exception:
        _finish({"error": traceback.format_exc()})


def _finish(result):
    import substance_painter.application
    import substance_painter.project as sp_project

    close_plugin()
    with open(OUT, "w") as handle:
        json.dump(result, handle, indent=2)
    try:
        if sp_project.is_open():
            sp_project.close()
    finally:
        substance_painter.application.close()
