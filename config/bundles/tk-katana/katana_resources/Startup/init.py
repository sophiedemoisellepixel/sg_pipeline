"""
Katana startup script: starts the Toolkit engine inside Katana.

Katana runs Startup/init.py of every folder listed in KATANA_RESOURCES when it
starts; the launcher adds this folder. It reads:

    SGTK_CORE_PYTHON_PATH          where to import sgtk from (required)
    SGTK_CONTEXT                   serialized context from the desktop app, or
    SHOTGUN_ENTITY_TYPE / _ID      the entity to start in (e.g. Task 5827)
    SHOTGUN_BUNDLE_CACHE_FALLBACK_PATHS   extra bundle caches (optional, read by tk-core)

If SGTK_CORE_PYTHON_PATH is not set Katana was started normally and the script
does nothing. The engine is started once Katana has finished starting up, so
that the main window and its menu bar exist.

Katana does not keep this script's globals alive for the callback, so
start_toolkit() imports and defines everything it needs itself.
"""

import logging
import os
import sys
import traceback

from Callbacks import Callbacks


def start_toolkit(*args, **kwargs):
    import logging
    import os
    import sys
    import traceback

    ENGINE_NAME = "tk-katana"
    PLUGIN_ID = "basic.katana"
    BASE_CONFIGURATION = "sgtk:descriptor:app_store?name=tk-config-basic"
    log = logging.getLogger("FlowProductionTracking")

    def _launch_entity(sgtk):
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
                "desktop app, then restart Katana."
            )

        manager = sgtk.bootstrap.ToolkitManager(user)
        manager.plugin_id = PLUGIN_ID
        manager.base_configuration = BASE_CONFIGURATION
        engine = manager.bootstrap_engine(ENGINE_NAME, entity=_launch_entity(sgtk))
        log.info("Flow Production Tracking started in %s" % engine.context)
        return engine
    except Exception:
        log.error("Could not start Flow Production Tracking:\n%s" % traceback.format_exc())
        return None


if os.environ.get("SGTK_CORE_PYTHON_PATH"):
    Callbacks.addCallback(Callbacks.Type.onStartupComplete, start_toolkit)
