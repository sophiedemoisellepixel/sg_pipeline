"""
Mari startup script: starts the Toolkit engine inside Mari.

Mari runs every script in the folders listed in MARI_SCRIPT_PATH when it
starts; the launcher adds this folder. It reads:

    SGTK_CORE_PYTHON_PATH          where to import sgtk from (required)
    SGTK_CONTEXT                   serialized context from the desktop app, or
    SHOTGUN_ENTITY_TYPE / _ID      the entity to start in (e.g. Task 5827)
    SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS   extra bundle caches (optional, read by tk-core)

If SGTK_CORE_PYTHON_PATH is not set Mari was started normally and the script
does nothing.
"""

import os
import sys
import traceback

import mari

ENGINE_NAME = "tk-mari"
PLUGIN_ID = "basic.mari"
BASE_CONFIGURATION = "sgtk:descriptor:app_store?name=tk-config-basic"


def _launch_entity(sgtk):
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


def start_toolkit():
    core_python = os.environ.get("SGTK_CORE_PYTHON_PATH")
    if not core_python:
        return None

    try:
        if core_python not in sys.path:
            sys.path.insert(0, core_python)
        import sgtk

        if sgtk.platform.current_engine() is not None:
            return sgtk.platform.current_engine()

        sgtk.LogManager().initialize_base_file_handler(ENGINE_NAME)

        user = sgtk.authentication.ShotgunAuthenticator().get_default_user()
        if user is None:
            raise RuntimeError(
                "Not signed in. Sign in with the Flow Production Tracking "
                "desktop app, then restart Mari."
            )

        manager = sgtk.bootstrap.ToolkitManager(user)
        manager.plugin_id = PLUGIN_ID
        manager.base_configuration = BASE_CONFIGURATION
        engine = manager.bootstrap_engine(ENGINE_NAME, entity=_launch_entity(sgtk))
        mari.app.log("[sgtk] Flow Production Tracking started in %s" % engine.context)
        return engine
    except Exception:
        mari.app.log(
            "[sgtk] Could not start Flow Production Tracking:\n%s" % traceback.format_exc()
        )
        return None


start_toolkit()
