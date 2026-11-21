"""
Substance 3D Painter startup plugin: starts the Toolkit engine inside Painter.

Painter loads this because the launcher adds its parent folder to
SUBSTANCE_PAINTER_PLUGINS_PATH. It reads:

    SGTK_CORE_PYTHON_PATH          where to import sgtk from (required)
    SGTK_CONTEXT                   serialized context from the desktop app, or
    SHOTGUN_ENTITY_TYPE / _ID      the entity to start in (e.g. Task 5827)
    SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS   extra bundle caches (optional, read by tk-core)

If SGTK_CORE_PYTHON_PATH is not set Painter was started normally and the plugin
does nothing.
"""

import os
import sys
import traceback

import substance_painter.logging

ENGINE_NAME = "tk-substancepainter"
PLUGIN_ID = "basic.substancepainter"
BASE_CONFIGURATION = "sgtk:descriptor:app_store?name=tk-config-basic"

_engine = None


def start_plugin():
    global _engine

    core_python = os.environ.get("SGTK_CORE_PYTHON_PATH")
    if not core_python:
        return

    try:
        if core_python not in sys.path:
            sys.path.insert(0, core_python)
        import sgtk

        sgtk.LogManager().initialize_base_file_handler(ENGINE_NAME)

        user = sgtk.authentication.ShotgunAuthenticator().get_default_user()
        if user is None:
            raise RuntimeError(
                "Not signed in. Sign in with the Flow Production Tracking "
                "desktop app, then restart Painter."
            )

        manager = sgtk.bootstrap.ToolkitManager(user)
        manager.plugin_id = PLUGIN_ID
        manager.base_configuration = BASE_CONFIGURATION
        # SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS, set by the launcher, is read by
        # the manager itself.

        _engine = manager.bootstrap_engine(ENGINE_NAME, entity=_launch_entity(sgtk, user))
        substance_painter.logging.info(
            "[sgtk] Flow Production Tracking started in %s" % _engine.context
        )
    except Exception:
        substance_painter.logging.error(
            "[sgtk] Could not start Flow Production Tracking:\n%s" % traceback.format_exc()
        )


def close_plugin():
    global _engine
    if _engine is not None:
        try:
            _engine.destroy()
        except Exception:
            substance_painter.logging.warning(
                "[sgtk] Error while shutting down:\n%s" % traceback.format_exc()
            )
        _engine = None


def _launch_entity(sgtk, user):
    """The entity to start the engine in, from the launch environment."""
    serialized = os.environ.get("SGTK_CONTEXT")
    if serialized:
        context = sgtk.context.deserialize(serialized)
        entity = context.task or context.entity or context.project
        if entity:
            return {"type": entity["type"], "id": entity["id"]}

    entity_type = os.environ.get("SHOTGUN_ENTITY_TYPE")
    entity_id = os.environ.get("SHOTGUN_ENTITY_ID")
    if entity_type and entity_id:
        return {"type": entity_type, "id": int(entity_id)}

    raise RuntimeError(
        "No context to start in: set SGTK_CONTEXT, or SHOTGUN_ENTITY_TYPE and "
        "SHOTGUN_ENTITY_ID."
    )
